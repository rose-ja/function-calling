from __future__ import annotations

from typing import Any

from tool_core import ToolResult


WEATHER_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "查询支持城市的模拟天气；只读取数据，不修改任何业务信息",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {
                    "type": "string",
                    "description": "城市名称，例如北京或上海",
                    "minLength": 1,
                },
            },
            "required": ["city"],
            "additionalProperties": False,
        },
    },
}

SUPPORTED_WEATHER = {
    "北京": {
        "condition": "rain",
        "temperature_celsius": 22,
    },
    "上海": {
        "condition": "cloudy",
        "temperature_celsius": 25,
    },
}


def execute_weather(arguments: Any) -> ToolResult:
    if not isinstance(arguments, dict):
        return ToolResult.failure(
            "INVALID_ARGUMENTS",
            "工具参数必须是 JSON 对象",
        )

    if set(arguments) != {"city"}:
        return ToolResult.failure(
            "INVALID_ARGUMENTS",
            "参数必须且只能包含 city",
        )

    city = arguments["city"]
    if not isinstance(city, str) or not city.strip():
        return ToolResult.failure(
            "INVALID_ARGUMENTS",
            "city 必须是非空字符串",
        )

    normalized_city = city.strip()
    weather = SUPPORTED_WEATHER.get(normalized_city)
    if weather is None:
        return ToolResult.failure(
            "CITY_NOT_SUPPORTED",
            f"暂不支持查询城市：{normalized_city}",
        )

    return ToolResult.success(
        {
            "city": normalized_city,
            "condition": weather["condition"],
            "temperature_celsius": weather["temperature_celsius"],
        }
    )