from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    data: dict[str, Any] | None = None
    error_type: str | None = None
    message: str | None = None

    @classmethod
    def success(cls, data: dict[str, Any]) -> "ToolResult":
        return cls(ok=True, data=data)

    @classmethod
    def failure(
        cls,
        error_type: str,
        message: str,
    ) -> "ToolResult":
        return cls(
            ok=False,
            error_type=error_type,
            message=message,
        )


ToolFunction = Callable[[dict[str, Any]], ToolResult]


def get_weather(arguments: dict[str, Any]) -> ToolResult:
    city = arguments.get("city")

    if not isinstance(city, str) or not city.strip():
        return ToolResult.failure(
            error_type="INVALID_ARGUMENTS",
            message="city 必须是非空字符串",
        )

    return ToolResult.success(
        {
            "city": city.strip(),
            "condition": "rain",
            "temperature_celsius": 22,
        }
    )


TOOL_REGISTRY: dict[str, ToolFunction] = {
    "get_weather": get_weather,
}


def dispatch_tool(
    tool_name: Any,
    arguments: Any,
) -> ToolResult:
    if not isinstance(tool_name, str) or not tool_name.strip():
        return ToolResult.failure(
            error_type="INVALID_TOOL_NAME",
            message="工具名必须是非空字符串",
        )

    tool = TOOL_REGISTRY.get(tool_name.strip())
    if tool is None:
        return ToolResult.failure(
            error_type="UNKNOWN_TOOL",
            message=f"未注册的工具：{tool_name}",
        )

    if not isinstance(arguments, dict):
        return ToolResult.failure(
            error_type="INVALID_ARGUMENTS",
            message="工具参数必须是对象",
        )

    try:
        return tool(arguments)
    except Exception:
        # 对外隐藏内部堆栈，避免暴露实现细节。
        return ToolResult.failure(
            error_type="INTERNAL_ERROR",
            message="工具执行失败",
        )


def main() -> None:
    model_output = {
        "tool_name": "get_weather",
        "arguments": {"city": "北京"},
    }

    result = dispatch_tool(
        model_output["tool_name"],
        model_output["arguments"],
    )

    print(result)


if __name__ == "__main__":
    main()