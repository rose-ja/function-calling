from __future__ import annotations

from collections.abc import Callable
from typing import Any

from tool_core import ToolResult
from weather_tool import execute_weather


ToolFunction = Callable[[Any], ToolResult]

TOOL_REGISTRY: dict[str, ToolFunction] = {
    "get_weather": execute_weather,
}


def dispatch_tool(tool_name: Any, arguments: Any) -> ToolResult:
    if not isinstance(tool_name, str) or not tool_name.strip():
        return ToolResult.failure(
            "INVALID_TOOL_NAME",
            "工具名必须是非空字符串",
        )

    # 只有注册过的函数可以由模型请求；不根据字符串动态寻找函数。
    tool = TOOL_REGISTRY.get(tool_name)
    if tool is None:
        return ToolResult.failure(
            "UNKNOWN_TOOL",
            f"未注册的工具：{tool_name}",
        )

    try:
        result = tool(arguments)
    except Exception:
        # 内部异常应另行记录日志，不把堆栈直接交给模型。
        return ToolResult.failure(
            "INTERNAL_ERROR",
            "工具执行时发生内部错误",
        )

    if not isinstance(result, ToolResult):
        return ToolResult.failure(
            "INTERNAL_ERROR",
            "工具返回了无效结果",
        )

    return result


def main() -> None:
    examples = [
        {"tool_name": "get_weather", "arguments": {"city": "北京"}},
        {"tool_name": "search_weather", "arguments": {"city": "北京"}},
        {"tool_name": "get_weather", "arguments": {"city": ""}},
    ]

    for model_output in examples:
        result = dispatch_tool(
            model_output["tool_name"],
            model_output["arguments"],
        )
        print(model_output["tool_name"], result)


if __name__ == "__main__":
    main()