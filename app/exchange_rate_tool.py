from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from tool_core import ErrorType, ToolResult
from tool_spec import ToolSpec

MONEY_QUANTUM = Decimal("0.01")

# 币种只约束“格式”，不把支持范围写进 Schema。
# 原因：支持范围是会变动的业务数据，复制进 Schema 会让模型上下文跟着数据膨胀。
EXCHANGE_RATE_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "base_currency": {
            "type": "string",
            "description": "基础币种，三位大写字母代码，例如 CNY 或 USD",
            "pattern": r"^[A-Z]{3}$",
        },
        "quote_currency": {
            "type": "string",
            "description": "报价币种，三位大写字母代码，例如 USD 或 JPY",
            "pattern": r"^[A-Z]{3}$",
        },
        "amount": {
            "type": "number",
            "description": "可选：待换算金额，必须大于 0",
            "exclusiveMinimum": 0,
        },
    },
    "required": ["base_currency", "quote_currency"],
    "additionalProperties": False,
}

# 汇率用字符串保存，避免 0.14 这类十进制小数在二进制浮点里失真。
SUPPORTED_RATES: dict[tuple[str, str], str] = {
    ("CNY", "USD"): "0.14",
    ("USD", "CNY"): "7.12",
    ("CNY", "JPY"): "20.5",
    ("USD", "JPY"): "146.8",
}

def execute_exchange_rate(arguments: dict[str, Any]) -> ToolResult:
    """只处理业务规则：币种格式已由 tool_schema 校验过。"""
    base_currency = arguments["base_currency"]
    quote_currency = arguments["quote_currency"]

    if base_currency == quote_currency:
        # 同币种不需要外部报价，比率恒为 1。
        rate = Decimal("1")
    else:
        raw_rate = SUPPORTED_RATES.get((base_currency, quote_currency))
        if raw_rate is None:
            # 不做反向推导：方向确实影响汇率，隐式换算会让模型误以为所有组合都支持。
            return ToolResult.failure(
                ErrorType.RATE_NOT_SUPPORTED,
                f"暂不支持 {base_currency} 到 {quote_currency} 的汇率",
            )
        rate = Decimal(raw_rate)

    data: dict[str, Any] = {
        "base_currency": base_currency,
        "quote_currency": quote_currency,
        "rate": str(rate),
    }

    amount = arguments.get("amount")
    if amount is not None:
        # 金额用 Decimal 运算，避免二进制浮点误差；对外用字符串传输，避免精度丢失。
        decimal_amount = Decimal(str(amount))
        converted = (decimal_amount * rate).quantize(
            MONEY_QUANTUM,
            rounding=ROUND_HALF_UP,
        )
        data["amount"] = str(decimal_amount)
        data["converted_amount"] = str(converted)

    return ToolResult.success(data)

EXCHANGE_RATE_TOOL = ToolSpec(
    name="get_exchange_rate",
    description="查询两种币种之间的模拟汇率，可选按金额换算；只读取数据",
    parameters=EXCHANGE_RATE_PARAMETERS,
    handler=execute_exchange_rate,
    risk_level="read",
    timeout_seconds=3.0,
    retryable_on_timeout=True,
)