from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import Context, ContextVar, Token
from dataclasses import dataclass
from contextvars import copy_context


@dataclass(frozen=True)
class RequestContext:
    """一次请求的身份信息。

    actor_id 必须来自已验证的会话，绝不能来自模型生成的工具参数。
    """

    actor_id: str
    session_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.actor_id, str) or not self.actor_id.strip():
            raise ValueError("actor_id 必须是非空字符串")
        if not isinstance(self.session_id, str) or not self.session_id.strip():
            raise ValueError("session_id 必须是非空字符串")

    def idempotency_key(self, tool_name: str, request_id: str) -> str:
        """幂等键由应用拼装：会话 + 工具 + 请求标识。

        带上会话是为了避免跨用户碰撞，带上工具名是为了避免同一请求
        在多个工具间被误认为同一次业务操作。
        """
        if not isinstance(tool_name, str) or not tool_name.strip():
            raise ValueError("tool_name 必须是非空字符串")
        if not isinstance(request_id, str) or not request_id.strip():
            raise ValueError("request_id 必须是非空字符串")
        return f"{self.session_id}:{tool_name}:{request_id}"


class MissingIdentityError(RuntimeError):
    """工具在没有请求身份的情况下被调用。"""


_CURRENT: ContextVar[RequestContext | None] = ContextVar(
    "current_request_context",
    default=None,
)


def current_context() -> RequestContext:
    context = _CURRENT.get()
    if context is None:
        raise MissingIdentityError("当前没有请求身份")
    return context


@contextmanager
def use_context(context: RequestContext) -> Iterator[RequestContext]:
    """在代码块内设置请求身份，退出时自动还原。"""
    if not isinstance(context, RequestContext):
        raise TypeError("context 必须是 RequestContext")

    token: Token = _CURRENT.set(context)
    try:
        yield context
    finally:
        _CURRENT.reset(token)


def capture_for_thread() -> Context:
    """捕获当前上下文，供线程池里的任务使用。

    ThreadPoolExecutor 不会自动继承 ContextVar：工作线程拿到的是一个空上下文。
    因此必须在提交任务之前 copy_context()，再把 Context.run 交给线程池。
    """
    return copy_context()
