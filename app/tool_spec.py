from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from tool_core import ErrorType, ToolResult
from tool_schema import validate_arguments

RiskLevel = Literal["read", "write"]

ToolHandler = Callable[[dict[str, Any]], ToolResult]

@dataclass(frozen=True)
class ToolSpec:
    """工具的完整定义：既是给模型的契约，也是应用层的治理元数据。"""
    
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler
    risk_level: RiskLevel = "read"
    requires_confirmation: bool = False
    timeout_seconds: float = 5.0
    retryable_on_timeout: bool = False
    
    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("工具名必须是非空字符串")
        if not isinstance(self.description, str) or not self.description.strip():
            raise ValueError("工具描述必须是非空字符串")
        if not isinstance(self.parameters, dict) or self.parameters.get("type") != "object":
            raise ValueError("parameters 必须是 type=object 的 JSON Schema")
        if self.risk_level not in ("read", "write"):
            raise ValueError("risk_level 只能是 read 或 write")
        if not callable(self.handler):
            raise TypeError("handler 必须可调用")
        if self.requires_confirmation and self.risk_level != "write":
            raise ValueError("只有写入工具才需要用户确认")
        if not isinstance(self.timeout_seconds, (int, float)) or isinstance(
            self.timeout_seconds, bool
        ):
            raise TypeError("timeout_seconds 必须是数字")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds 必须大于 0")
        if not isinstance(self.retryable_on_timeout, bool):
            raise TypeError("retryable_on_timeout 必须是布尔值")
        if self.retryable_on_timeout and self.risk_level != "read":
            raise ValueError("写入工具超时后不允许直接重试，必须先确认执行状态")
        
    def to_model_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }
        
def run_tool(spec: ToolSpec, arguments: Any) -> ToolResult:
    """结构校验前置，因此 handler 可以信任入参已经是一个合法字典。"""
    issues = validate_arguments(spec.parameters, arguments)
    if issues:
        detail = "；".join(issue.describe() for issue in issues)
        return ToolResult.failure(ErrorType.INVALID_ARGUMENTS, detail)

    return spec.handler(arguments)