from __future__ import annotations

from typing import Any

from tool_core import ErrorType, ToolResult
from tool_spec import ToolSpec, run_tool
from weather_tool import WEATHER_TOOL
from exchange_rate_tool import EXCHANGE_RATE_TOOL
from search_tool import SEARCH_TOOL
from guard import run_with_guard

TOOL_REGISTRY: dict[str, ToolSpec] = {
    spec.name: spec
    for spec in (WEATHER_TOOL, EXCHANGE_RATE_TOOL, SEARCH_TOOL)
}

def dispatch_tool(
    tool_name: Any,
    arguments: Any,
    *,
    confirmed: bool = False,
    idempotency_key: str | None = None,
    registry: dict[str, ToolSpec] | None = None,
) -> ToolResult:
    """把模型给出的工具名和参数当作不可信输入，逐层检查后才允许执行。"""
    specs = TOOL_REGISTRY if registry is None else registry
    
    # 1. 工具名本身必须是一个像样的字符串。
    if not isinstance(tool_name, str) or not tool_name.strip():
        return ToolResult.failure(
            ErrorType.INVALID_TOOL_NAME,
            "工具名必须是非空字符串",
        )
        
    # 2. 只允许调用注册表中声明的工具，不按字符串动态查找函数。
    spec = specs.get(tool_name.strip())
    if spec is None:
        return ToolResult.failure(
            ErrorType.UNKNOWN_TOOL,
            f"未注册的工具：{tool_name}",
        )
        
    # 3. 风险策略由应用判断，模型无法通过参数绕过。
    if spec.requires_confirmation and not confirmed:
        return ToolResult.failure(
            ErrorType.CONFIRMATION_REQUIRED,
            f"{spec.name} 会修改业务数据，需要用户确认",
        )
        
    # 4. 幂等键检查、参数校验、超时与重试统一交给治理层。
    try:
        return run_with_guard(
            spec,
            arguments,
            idempotency_key=idempotency_key,
        )
    except Exception:
        # 治理层未预料的异常在入口兜底，绝不把堆栈交给模型。
        return ToolResult.failure(
            ErrorType.INTERNAL_ERROR,
            "工具执行时发生内部错误",
        )