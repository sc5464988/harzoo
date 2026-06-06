"""交互式配置向导：选模型、填 Key、挑工具，一行命令完成部署。"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any

# ── 模型预设 ──────────────────────────────────────────────

PROVIDERS: dict[str, dict[str, str]] = {
    "1": {
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "default_model": "deepseek-chat",
    },
    "2": {
        "name": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o",
    },
    "3": {
        "name": "Qwen / DashScope",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "default_model": "qwen-plus",
    },
    "4": {
        "name": "Custom (OpenAI-compatible)",
        "base_url": "",
        "default_model": "",
    },
}

# 工具名 → (文件名, 危险等级, 简介)
ALL_TOOLS: list[tuple[str, str, int, str]] = [
    ("Shell", "shell.py", 1, "Run shell commands — high risk"),
    ("Write", "write.py", 1, "Write files — modifies disk"),
    ("Edit", "edit.py", 1, "In-place text replacement — modifies files"),
    ("WebFetch", "webfetch.py", 1, "Fetch web pages — network access"),
    ("SubtaskAgent", "subagent.py", 1, "Spawn sub-agent — delegates work"),
    ("Read", "read.py", 0, "Read files — safe"),
    ("Glob", "glob.py", 0, "Find files by pattern — safe"),
    ("Grep", "grep.py", 0, "Search file contents — safe"),
    ("CompactContext", "compact_context.py", 0, "Summarize chat history — safe"),
]

TOOLS_ROOT = Path(__file__).resolve().parent.parent.parent / "assets" / "config" / "tools"


def _prompt(prompt_text: str, default: str = "") -> str:
    if default:
        result = input(f"  {prompt_text} [{default}]: ").strip()
        return result or default
    while True:
        result = input(f"  {prompt_text}: ").strip()
        if result:
            return result
        print("  (required)")


def _prompt_yn(prompt_text: str, default: str = "y") -> bool:
    yn = "Y/n" if default == "y" else "y/N"
    result = input(f"  {prompt_text} [{yn}]: ").strip().lower()
    if not result:
        result = default
    return result in ("y", "yes")


def run_setup() -> None:
    config_root = Path.home() / ".harzoo" / "config"

    print()
    print("=" * 60)
    print("  Harzoo Setup — 5 minutes to your first agent")
    print("=" * 60)
    print()
    print("  This will:")
    print("    1. Pick an LLM provider")
    print("    2. Configure your API key")
    print("    3. Choose your tools")
    print("    4. Write everything to ~/.harzoo/config/")
    print()

    # ── Step 1: Provider ────────────────────────────────
    print("─" * 60)
    print("  Step 1/4 — Choose your LLM provider")
    print()
    for key, info in PROVIDERS.items():
        extra = ""
        if info["default_model"]:
            extra = f" (default: {info['default_model']})"
        print(f"    [{key}] {info['name']}{extra}")
    print()
    provider_key = _prompt("Select", default="1")
    if provider_key not in PROVIDERS:
        print(f"  Invalid choice '{provider_key}', using DeepSeek")
        provider_key = "1"
    provider = PROVIDERS[provider_key]

    # ── Step 2: API Key + Model ─────────────────────────
    print()
    print("─" * 60)
    print(f"  Step 2/4 — {provider['name']} configuration")
    print()

    if provider_key == "4":
        base_url = _prompt("Base URL")
        model = _prompt("Model name")
    else:
        base_url = provider["base_url"]
        print(f"  Endpoint: {base_url}")
        model = _prompt("Model name", default=provider["default_model"])

    api_key = _prompt("API key")
    profile_name = _prompt("Profile name", default="default")

    # ── Step 3: Tools ──────────────────────────────────
    print()
    print("─" * 60)
    print("  Step 3/4 — Select tools")
    print()
    print("  [1] Dangerous tools — can modify files, run commands, access network")
    print("      Each requires one-time approval per session.")
    print("  [2] Safe tools — read, search, summarize (no prompts)")
    print()
    dangerous = [t for t in ALL_TOOLS if t[2] == 1]
    safe = [t for t in ALL_TOOLS if t[2] == 0]

    print("  ── Dangerous (confirm on first use) ──")
    for i, (name, _, _, desc) in enumerate(dangerous):
        yn = "y" if name in ("Shell", "Read", "Write", "Edit", "WebFetch") else "n"
        if _prompt_yn(f"[ ] {name} — {desc}", default=yn):
            pass  # include
        else:
            dangerous[i] = None  # type: ignore[assignment]

    print()
    print("  ── Safe (always auto-allow) ──")
    for i, (name, _, _, desc) in enumerate(safe):
        if _prompt_yn(f"[ ] {name} — {desc}", default="y"):
            pass
        else:
            safe[i] = None  # type: ignore[assignment]

    selected_tools: list[str] = [
        t[0] for t in dangerous if t is not None
    ] + [
        t[0] for t in safe if t is not None
    ]

    if not selected_tools:
        print()
        print("  You didn't select any tools. Adding Read at minimum.")
        selected_tools = ["Read"]

    # ── Step 4: Generate ───────────────────────────────
    print()
    print("─" * 60)
    print("  Step 4/4 — Writing config")
    print()

    config_root.mkdir(parents=True, exist_ok=True)
    (config_root / "profiles").mkdir(exist_ok=True)
    (config_root / "tools").mkdir(exist_ok=True)
    (config_root / "skills").mkdir(exist_ok=True)

    profile_content = _render_profile(
        name=profile_name,
        description=f"Profile for {provider['name']} / {model}",
        api_key=api_key,
        base_url=base_url,
        model_name=model,
        tool_names=selected_tools,
    )
    profile_path = config_root / "profiles" / f"{profile_name}.md"
    profile_path.write_text(profile_content, encoding="utf-8")

    config_json = {"startup_profile": f"{profile_name}.md"}
    (config_root / "config.json").write_text(
        json.dumps(config_json, indent=2), encoding="utf-8"
    )

    # Copy tool files
    if TOOLS_ROOT.is_dir():
        for f in TOOLS_ROOT.glob("*.py"):
            shutil.copy2(f, config_root / "tools" / f.name)

    print(f"  Profile:   {profile_path}")
    print(f"  Tools:     {config_root / 'tools'} ({len(selected_tools)} enabled)")
    print(f"  Config:    {config_root / 'config.json'}")
    print()
    print("=" * 60)
    print("  Setup complete. Run:  harzoo")
    print("=" * 60)
    print()


def _render_profile(
    *,
    name: str,
    description: str,
    api_key: str,
    base_url: str,
    model_name: str,
    tool_names: list[str],
) -> str:
    tool_list = ", ".join(tool_names)
    lines = [
        "---",
        f'profile_version: "2026-05-27"',
        f"name: {name}",
        f"description: {description}",
        f"api_key: {api_key}",
        f"base_url: {base_url}",
        f"model_name: {model_name}",
        "max_context_tokens: 128000",
        f"tool_names: {tool_list}",
        "",
        "skill_names:",
        "subagent_names:",
        "",
        "---",
        "",
        "## 角色",
        "",
        "你是 Harzoo 智能助手。高效、可靠、简洁地完成任务。",
        "",
        "## 原则",
        "",
        "- 直接给出答案，不拖泥带水",
        "- 必要时使用工具",
        "- 不确定时主动提问",
    ]
    return "\n".join(lines) + "\n"
