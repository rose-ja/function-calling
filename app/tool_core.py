from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

ToolStatus = Literal["success", "error"]

@dataclass(frozen=True)
class ToolError:
    type: str
    message: str
    retryable: bool
    
    def __post_init__(self) -> None:
        if not isinstance(self.type, str) or not self.type.strip():
            raise ValueError("type 必须是非空字符串")
        if not isinstance(self.message, str) or not self.message.strip():
            raise ValueError("message 必须是非空字符串")
        if not isinstance(self.retryable, bool):
            raise ValueError("retryable 必须是布尔值")
        
@dataclass(frozen=True)
class ToolResult:
    status: ToolStatus
    data: dict[str, Any] | None = None
    error: ToolError | None = None

    def __post_init__(self) -> None:
        if self.status == "success":
            if not isinstance(self.data, dict) or self.error is not None:
                raise ValueError("成功结果必须包含数据，且不能包含错误")
        elif self.status == "error":
            if self.error is None or self.data is not None:
                raise ValueError("失败结果必须包含错误，且不能包含数据")
        else:
            raise ValueError("未知的工具结果状态")
        
    @classmethod
    def success(cls, data: dict[str, Any]) -> ToolResult:
        return cls(status="success", data=data)
    
    @classmethod
    def failure(
        cls,
        error_type: str,
        message: str,
        retryable: bool = False,
    ) -> ToolResult:
        return cls(
            status="error",
            error=ToolError(
                type=error_type,
                message=message,
                retryable=retryable,
            ),
        )