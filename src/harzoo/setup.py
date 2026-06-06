"""交互式配置向导：选模型、填 Key，搞定就走。"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

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

ALL_TOOLS = [
    "Shell", "Write", "Edit", "WebFetch", "SubtaskAgent",
    "Read", "Glob", "Grep", "CompactContext",
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


def run_setup() -> None:
    config_root = Path.home() / ".harzoo" / "config"

    print()
    print("=" * 60)
    print("  Harzoo Setup")
    print("=" * 60)
    print()

    # ── Step 1: Provider ────────────────────────────────
    print("  Choose your LLM provider:")
    print()
    for key, info in PROVIDERS.items():
        extra = ""
        if info["default_model"]:
            extra = f" (default model: {info['default_model']})"
        print(f"    [{key}] {info['name']}{extra}")
    print()
    provider_key = _prompt("Select", default="1")
    if provider_key not in PROVIDERS:
        print(f"  Unknown '{provider_key}', using DeepSeek")
        provider_key = "1"
    provider = PROVIDERS[provider_key]

    # ── Step 2: API Key + Model ─────────────────────────
    print()
    print("─" * 60)
    print()

    if provider_key == "4":
        base_url = _prompt("Base URL")
        model = _prompt("Model name")
    else:
        base_url = provider["base_url"]
        model = _prompt("Model name", default=provider["default_model"])

    api_key = _prompt("API key")
    profile_name = _prompt("Profile name", default="default")

    # ── Generate ─────────────────────────────────────────
    print()
    print("─" * 60)
    print("  Writing config...")
    print()

    config_root.mkdir(parents=True, exist_ok=True)
    (config_root / "profiles").mkdir(exist_ok=True)
    (config_root / "tools").mkdir(exist_ok=True)
    (config_root / "skills").mkdir(exist_ok=True)

    tool_list = ", ".join(ALL_TOOLS)
    profile_content = (
        "---\n"
        f'profile_version: "2026-05-27"\n'
        f"name: {profile_name}\n"
        f"description: Profile for {provider['name']} / {model}\n"
        f"api_key: {api_key}\n"
        f"base_url: {base_url}\n"
        f"model_name: {model}\n"
        "max_context_tokens: 128000\n"
        f"tool_names: {tool_list}\n"
        "\n"
        "skill_names:\n"
        "subagent_names:\n"
        "\n"
        "---\n"
        "\n"
        "## 角色\n"
        "\n"
        "你是 Harzoo 智能助手。高效、可靠、简洁地完成任务。\n"
        "\n"
        "## 原则\n"
        "\n"
        "- 直接给出答案，不拖泥带水\n"
        "- 必要时使用工具\n"
        "- 不确定时主动提问\n"
    )

    profile_path = config_root / "profiles" / f"{profile_name}.md"
    profile_path.write_text(profile_content, encoding="utf-8")

    config_json = {"startup_profile": f"{profile_name}.md"}
    (config_root / "config.json").write_text(json.dumps(config_json, indent=2), encoding="utf-8")

    if TOOLS_ROOT.is_dir():
        for f in TOOLS_ROOT.glob("*.py"):
            shutil.copy2(f, config_root / "tools" / f.name)

    print(f"  Profile:  {profile_path}")
    print(f"  Tools:    {len(ALL_TOOLS)} enabled (dangerous tools confirmed on first use)")
    print()
    print("=" * 60)
    print("  Done. Run:  harzoo")
    print("=" * 60)
    print()
