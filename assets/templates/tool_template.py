"""SHORT_DESCRIPTION."""

from __future__ import annotations

from typing import Any

TOOL_VERSION = "YYYY-MM-DD"

from harzoo.agent.kernel.tool import Context, Tool, ToolResult


class MyTool(Tool):
    name = "MyTool"
    description = "One-line description."
    parameters = {
        "type": "object",
        "properties": {
            "input": {
                "type": "string",
                "description": "Parameter description",
            },
        },
        "required": ["input"],
    }

    def execute(self, *, input: str, ctx: Context | None = None, **_: Any) -> ToolResult:
        if not input.strip():
            return ToolResult.failure("input must not be empty", code="INVALID_ARGUMENTS")
        # TODO: implement
        return ToolResult.success({"result": input})

TOOL = MyTool
