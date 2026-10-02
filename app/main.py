from __future__ import annotations

from typing import Any

from tool_core import ToolResult
from tool_spec import ToolSpec, run_tool
from weather_tool import WEATHER_TOOL


TOOL_REGISTRY: dict[str, ToolSpec] = {
    WEATHER_TOOL.name: WEATHER_TOOL,
}


def dispatch_tool(
    tool_name: Any,
    arguments: Any,
    *,
    confirmed: bool = False,
    registry: dict[str, ToolSpec] | None = None,
) -> ToolResult:
    specs = TOOL_REGISTRY if registry is None else registry

    if not isinstance(tool_name, str) or not tool_name.strip():
        return ToolResult.failure(
            "INVALID_TOOL_NAME",
            "工具名必须是非空字符串",
        )

    # 只允许调用注册表中声明的工具，不按字符串动态查找函数。
    spec = specs.get(tool_name.strip())
    if spec is None:
        return ToolResult.failure(
            "UNKNOWN_TOOL",
            f"未注册的工具：{tool_name}",
        )

    if spec.requires_confirmation and not confirmed:
        return ToolResult.failure(
            "CONFIRMATION_REQUIRED",
            f"{spec.name} 会修改业务数据，需要用户确认",
        )

    try:
        return run_tool(spec, arguments)
    except Exception:
        # 内部异常应写入日志，对外只返回不含堆栈的安全信息。
        return ToolResult.failure(
            "INTERNAL_ERROR",
            "工具执行时发生内部错误",
        )


def main() -> None:
    examples = [
        {"tool_name": "get_weather", "arguments": {"city": "北京"}},
        {"tool_name": "search_weather", "arguments": {"city": "北京"}},
        {"tool_name": "get_weather", "arguments": {"city": ""}},
        {"tool_name": "get_weather", "arguments": {"city": "北京", "force": True}},
    ]

    for model_output in examples:
        result = dispatch_tool(
            model_output["tool_name"],
            model_output["arguments"],
        )
        print(model_output["tool_name"], result)


if __name__ == "__main__":
    main()