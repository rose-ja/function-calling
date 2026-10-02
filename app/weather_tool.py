from __future__ import annotations

from typing import Any

from tool_core import ToolResult
from tool_spec import ToolSpec


# 这份 Schema 是唯一事实来源：既提供给模型，也用于运行时校验。
# pattern 在 JSON Schema 中是部分匹配，\S 表示至少包含一个非空白字符。
WEATHER_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "city": {
            "type": "string",
            "description": "城市名称，例如北京或上海",
            "minLength": 1,
            "pattern": r"\S",
        },
    },
    "required": ["city"],
    "additionalProperties": False,
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


def execute_weather(arguments: dict[str, Any]) -> ToolResult:
    city = arguments["city"].strip()

    weather = SUPPORTED_WEATHER.get(city)
    if weather is None:
        return ToolResult.failure(
            "CITY_NOT_SUPPORTED",
            f"暂不支持查询城市：{city}",
        )

    return ToolResult.success(
        {
            "city": city,
            "condition": weather["condition"],
            "temperature_celsius": weather["temperature_celsius"],
        }
    )


WEATHER_TOOL = ToolSpec(
    name="get_weather",
    description="查询支持城市的模拟天气；只读取数据，不修改任何业务信息",
    parameters=WEATHER_PARAMETERS,
    handler=execute_weather,
    risk_level="read",
)