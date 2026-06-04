"""Synchronous subtask agent tool (single-call delegated execution)."""


from __future__ import annotations

from pathlib import Path
from typing import Any

from harzoo.agent.agent import Agent
from harzoo.agent.components.paths import ConfigPaths, list_subagent_paths
from harzoo.agent.components.prompt import refresh_context_usage_slot
from harzoo.agent.components.util import load_yaml_front_matter_markdown
from harzoo.agent.kernel.message import assistant_message, tool_message, user_message
from harzoo.agent.kernel.tool import Context, Tool, ToolResult

TOOL_VERSION = "2026-05-22"


def _extract_final_assistant_content(state: list[dict[str, Any]]) -> Any:
    for item in reversed(state):
        if item.get("role") == "assistant":
            return item.get("content")
    return None


def _profile_search_candidates(paths: ConfigPaths) -> list[Path]:
    seen: set[Path] = set()
    ordered: list[Path] = []
    subagent_paths = list_subagent_paths(paths)
    for candidate in (
        paths.startup_profile_path,
        *sorted({p.resolve() for p in paths.profiles_root.glob("*.md") if p.is_file()}),
        *subagent_paths,
    ):
        resolved = candidate.resolve()
        if resolved not in seen:
            seen.add(resolved)
            ordered.append(resolved)
    return ordered


def _resolve_agent_profile_path(agent_name: str | None, paths: ConfigPaths) -> Path:
    if agent_name is None or not str(agent_name).strip():
        return paths.startup_profile_path.resolve()

    raw = str(agent_name).strip()
    expanded = Path(raw).expanduser()

    if expanded.is_absolute():
        resolved = expanded.resolve()
        if not resolved.is_file():
            raise FileNotFoundError(f"Profile not found: {resolved}")
        if resolved.suffix.lower() != ".md":
            raise ValueError(f"Profile must be a markdown file: {resolved}")
        return resolved

    under_profiles = (paths.profiles_root / expanded).resolve()
    if under_profiles.is_file():
        return under_profiles
    if under_profiles.suffix.lower() != ".md":
        with_suffix = under_profiles.with_suffix(".md")
        if with_suffix.is_file():
            return with_suffix

    stem = expanded.stem if expanded.suffix else raw
    direct = paths.profiles_root / f"{stem}.md"
    if direct.is_file():
        return direct.resolve()

    for candidate in list_subagent_paths(paths):
        if candidate.stem == stem or candidate.name == f"{stem}.md":
            return candidate.resolve()

    normalized = raw.lower()
    for candidate in _profile_search_candidates(paths):
        try:
            meta, _ = load_yaml_front_matter_markdown(candidate)
        except (OSError, ValueError):
            continue
        name = str(meta.get("name") or "").strip().lower()
        if name == normalized:
            return candidate.resolve()

    raise FileNotFoundError(
        f"Agent profile {raw!r} not found under {paths.profiles_root} (searched profiles directory)"
    )


class SubtaskAgentTool(Tool):
    """子任务委派工具：用子 profile 同步执行任务并回收最终结果。"""

    name = "SubtaskAgent"
    description = (
        "Run a delegated subtask with a dedicated profile in a synchronous nested "
        "agent loop, then return the final assistant output."
    )
    parameters = {
        "type": "object",
        "properties": {
            "task_description": {"type": "string", "description": "Subtask prompt for the delegated agent"},
            "agent_name": {
                "type": "string",
                "description": "Subtask profile name/path. Defaults to the active default profile.",
            },
            "max_turns": {
                "type": "integer",
                "description": "Maximum delegated loop turns before returning.",
                "minimum": 1,
                "maximum": 20,
                "default": 6,
            },
        },
        "required": ["task_description"],
    }

    def execute(
        self,
        task_description: str,
        agent_name: str | None = None,
        max_turns: int = 6,
        *,
        ctx: Context | None = None,
        **_: Any,
    ) -> ToolResult:
        task_text = str(task_description).strip()
        if not task_text:
            return ToolResult.failure("task_description is required", code="INVALID_ARGUMENTS")
        if ctx is None:
            return ToolResult.failure("SubtaskAgent requires host Context", code="INVALID_CONTEXT")

        try:
            capped_turns = max(1, min(20, int(max_turns)))
        except (TypeError, ValueError):
            return ToolResult.failure("max_turns must be an integer between 1 and 20", code="INVALID_ARGUMENTS")

        try:
            paths = ctx.config_paths
            profile_path = _resolve_agent_profile_path(agent_name, paths)
            child = Agent.from_profile(profile_path, paths)
        except Exception as exc:  # noqa: BLE001
            return ToolResult.failure(
                f"Failed to initialize subtask agent: {type(exc).__name__}: {exc}",
                code="SUBTASK_INIT_FAILED",
            )

        sub_state: list[dict[str, Any]] = [user_message([{"type": "text", "text": task_text}])]
        sub_ctx = Context(state=sub_state, agent=child, config_paths=paths)
        rounds = 0

        try:
            while rounds < capped_turns and sub_state and sub_state[-1].get("role") in ("user", "tool"):
                rounds += 1
                delta: list[dict[str, Any]] = []
                content, tool_calls, usage = child.decide(sub_state)
                delta.append(assistant_message(content=content, tool_calls=tool_calls))
                if isinstance(tool_calls, list) and tool_calls:
                    for tool_call in tool_calls:
                        call_id, fn = str(tool_call["id"]), tool_call["function"]
                        tool_name, args_str = str(fn["name"]), str(fn["arguments"])
                        tool_result = child.execute_tool_call(tool_name, args_str, sub_ctx)
                        delta.append(tool_message(call_id, tool_result))
                        if tool_result.injected_user_input_segments:
                            delta.append(user_message(tool_result.injected_user_input_segments))
                if not delta:
                    break
                sub_state.extend(delta)
                if usage:
                    child.llm.llm_config.system_prompt = refresh_context_usage_slot(
                        child.llm.llm_config.system_prompt,
                        usage_payload=usage,
                        max_context_tokens=child.llm.llm_config.max_context_tokens,
                    )
        except Exception as exc:  # noqa: BLE001
            return ToolResult.failure(
                f"Subtask execution failed: {type(exc).__name__}: {exc}",
                code="SUBTASK_EXECUTION_FAILED",
            )

        result_data = {
            "final_output": _extract_final_assistant_content(sub_state),
            "stopped_reason": "max_turns_reached"
            if rounds >= capped_turns and sub_state and sub_state[-1].get("role") in ("user", "tool")
            else "completed",
        }
        return ToolResult.success(result_data)


TOOL = SubtaskAgentTool
