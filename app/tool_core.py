from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal

ToolStatus = Literal["success", "error"]

class ErrorType(str, Enum):
    """错误码目录：新增一类失败就在这里登记，避免各处手写字符串拼错。"""
    
    # 分发与治理层
    INVALID_TOOL_NAME = "INVALID_TOOL_NAME"
    UNKNOWN_TOOL = "UNKNOWN_TOOL"
    INVALID_ARGUMENTS = "INVALID_ARGUMENTS"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    CONFIRMATION_REQUIRED = "CONFIRMATION_REQUIRED"
    TIMEOUT = "TIMEOUT"
    UPSTREAM_UNAVAILABLE = "UPSTREAM_UNAVAILABLE"
    INTERNAL_ERROR = "INTERNAL_ERROR"

    # 业务层
    CITY_NOT_SUPPORTED = "CITY_NOT_SUPPORTED"
    RATE_NOT_SUPPORTED = "RATE_NOT_SUPPORTED"
    INVALID_TIME_RANGE = "INVALID_TIME_RANGE"
    CALENDAR_CONFLICT = "CALENDAR_CONFLICT"
    
class ExecutionState(str, Enum):
    """写入类工具失败后，必须先回答“到底有没有生效”。"""

    NOT_EXECUTED = "not_executed"
    EXECUTED = "executed"
    UNKNOWN = "unknown"
    
@dataclass(frozen=True)
class ToolError:
    type: ErrorType
    message: str
    retryable: bool = False
    execution_state: ExecutionState = ExecutionState.NOT_EXECUTED
    
    def __post_init__(self) -> None:
        if not isinstance(self.type, ErrorType):
            raise TypeError("type 必须是 ErrorType")
        if not isinstance(self.message, str) or not self.message.strip():
            raise ValueError("message 必须是非空字符串")
        if not isinstance(self.retryable, bool):
            raise TypeError("retryable 必须是布尔值")
        if not isinstance(self.execution_state, ExecutionState):
            raise TypeError("execution_state 必须是 ExecutionState")
        
@dataclass(frozen=True)
class ToolResult:
    status: ToolStatus
    data: dict[str, Any] | None = None
    error: ToolError | None = None
    
    def __post_init__(self) -> None:
        if self.status == "success":
            if not isinstance(self.data, dict) or self.error is not None:
                raise ValueError("成功结果必须包含 data，且不能包含 error")
        elif self.status == "error":
            if self.error is None or self.data is not None:
                raise ValueError("失败结果必须包含 error，且不能包含 data")
        else:
            raise ValueError("未知的工具结果状态")
        
    @classmethod
    def success(cls, data: dict[str, Any]) -> ToolResult:
        return cls(status="success", data=data)
    
    @classmethod
    def failure(
        cls,
        error_type: ErrorType,
        message: str,
        *,
        retryable: bool = False,
        execution_state: ExecutionState = ExecutionState.NOT_EXECUTED,
    ) -> ToolResult:
        return cls(
            status="error",
            error=ToolError(
                type=error_type,
                message=message,
                retryable=retryable,
                execution_state=execution_state,
            ),
        )