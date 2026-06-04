"""Load skill instructions on demand from config/skills."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

TOOL_VERSION = "2026-05-27"

from harzoo.agent.components.paths import list_skill_manifests
from harzoo.agent.components.util import load_yaml_front_matter_markdown
from harzoo.agent.kernel.tool import Context, Tool, ToolResult


def _index_manifests(manifests: Sequence[Path]) -> dict[str, Path]:
    index: dict[str, Path] = {}
    for path in manifests:
        if not path.is_file():
            continue
        meta, _body = load_yaml_front_matter_markdown(path)
        name = str(meta.get("name") or "").strip()
        if not name:
            continue
        index[name.lower()] = path
    return index


def load_skill_from_disk(
    manifests: Sequence[Path],
    skill_name: str,
    *,
    allowed_names: Sequence[str],
    include_references: bool = False,
) -> dict[str, Any]:
    """按 name 加载 skill 正文；须通过 profile skill_names 白名单校验。"""

    allowed = {n.strip().lower() for n in allowed_names if n.strip()}
    normalized = skill_name.strip().lower()
    if normalized not in allowed:
        raise ValueError(f"Skill {skill_name!r} is not in profile skill_names")

    path = _index_manifests(manifests).get(normalized)
    if path is None:
        raise FileNotFoundError(f"Skill {skill_name!r} not found under configured skills")

    meta, body = load_yaml_front_matter_markdown(path)
    name = str(meta.get("name") or "").strip()
    description = " ".join(str(meta.get("description") or "").split()).strip()

    references: dict[str, str] = {}
    if include_references:
        ref_path = path.with_suffix(".reference.md")
        if ref_path.is_file():
            references[ref_path.name] = ref_path.read_text(encoding="utf-8")

    return {"name": name, "description": description, "body": body, "references": references}


class LoadSkillTool(Tool):
    """按名称加载允许的 Skill 正文，避免一次性加载全部技能内容。"""

    name = "LoadSkill"
    description = (
        "Load full instructions for an allowed skill by name from the Allowed Skills catalog. "
        "Call when the user's task matches a skill description, before proceeding."
    )
    parameters = {
        "type": "object",
        "properties": {
            "skill_name": {
                "type": "string",
                "description": "Skill name from the Allowed Skills catalog",
            },
            "include_references": {
                "type": "boolean",
                "description": "Also load <skill>.reference.md if present beside the skill file",
                "default": False,
            },
        },
        "required": ["skill_name"],
    }

    def __init__(self) -> None:
        self._loaded: set[str] = set()

    def execute(
        self,
        skill_name: str,
        include_references: bool = False,
        *,
        ctx: Context | None = None,
        **_: Any,
    ) -> ToolResult:
        if ctx is None:
            return ToolResult.failure("LoadSkill requires Context", code="INVALID_CONTEXT")

        normalized = skill_name.strip().lower()
        if not normalized:
            return ToolResult.failure("skill_name must not be empty", code="INVALID_ARGUMENTS")

        if normalized in self._loaded:
            return ToolResult.success(
                {
                    "name": skill_name.strip(),
                    "already_active": True,
                    "message": f"Skill {skill_name.strip()!r} is already loaded in this session.",
                }
            )

        try:
            loaded = load_skill_from_disk(
                list_skill_manifests(ctx.config_paths),
                skill_name,
                allowed_names=ctx.agent.profile.skill_names,
                include_references=include_references,
            )
        except ValueError as exc:
            return ToolResult.failure(str(exc), code="SKILL_NOT_ALLOWED")
        except FileNotFoundError as exc:
            return ToolResult.failure(str(exc), code="SKILL_NOT_FOUND")
        except Exception as exc:  # noqa: BLE001
            return ToolResult.failure(f"{type(exc).__name__}: {exc}", code="SKILL_LOAD_FAILED")

        self._loaded.add(normalized)
        data: dict[str, Any] = {
            "name": loaded["name"],
            "description": loaded["description"],
            "body": loaded["body"],
            "already_active": False,
        }
        if loaded["references"]:
            data["references"] = loaded["references"]
        return ToolResult.success(data)


TOOL = LoadSkillTool
