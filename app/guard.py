from __future__ import annotations

import threading
import time
from collections.abc import Callable
from concurrent.futures import Executor, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from dataclasses import dataclass

from tool_core import ErrorType, ExecutionState, ToolResult
from request_context import capture_for_thread
from tool_schema import validate_arguments
from tool_spec import ToolSpec, run_tool


@dataclass(frozen=True)
class RetryPolicy:
    """重试策略。次数、单次等待上限、总耗时预算三者都必须有界。"""

    max_attempts: int = 3
    base_delay_seconds: float = 0.2
    max_delay_seconds: float = 2.0
    total_budget_seconds: float = 5.0

    def __post_init__(self) -> None:
        if not isinstance(self.max_attempts, int) or isinstance(self.max_attempts, bool):
            raise TypeError("max_attempts 必须是整数")
        if self.max_attempts < 1:
            raise ValueError("max_attempts 至少为 1")
        for field_name, value in (
            ("base_delay_seconds", self.base_delay_seconds),
            ("max_delay_seconds", self.max_delay_seconds),
            ("total_budget_seconds", self.total_budget_seconds),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{field_name} 必须是数字")
            if value < 0:
                raise ValueError(f"{field_name} 不能为负数")
        if self.max_delay_seconds < self.base_delay_seconds:
            raise ValueError("max_delay_seconds 不能小于 base_delay_seconds")


class IdempotencyStore:
    """进程内幂等记录。

    真实系统必须把这份记录放在共享存储里（数据库唯一索引或 Redis），
    进程内字典只能防住单实例内的重复提交。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._results: dict[str, ToolResult] = {}
        self._in_flight: set[str] = set()

    def lookup(self, key: str) -> ToolResult | None:
        with self._lock:
            return self._results.get(key)

    def claim(self, key: str) -> bool:
        """抢占执行权。检查与占位在同一把锁内完成，避免并发请求重复执行。"""
        with self._lock:
            if key in self._results or key in self._in_flight:
                return False
            self._in_flight.add(key)
            return True

    def release(self, key: str) -> None:
        """放弃执行权：只在请求根本没进入执行时就该释放。"""
        with self._lock:
            self._in_flight.discard(key)

    def store(self, key: str, result: ToolResult) -> None:
        with self._lock:
            # setdefault：并发下先写入的结果为准，后到的结果不覆盖。
            self._results.setdefault(key, result)
            self._in_flight.discard(key)

    def clear(self) -> None:
        """清空全部记录。只给测试和演示使用。"""
        with self._lock:
            self._results.clear()
            self._in_flight.clear()


DEFAULT_IDEMPOTENCY_STORE = IdempotencyStore()

# 线程池全局复用。每次调用新建线程池会导致超时后无法回收线程。
_EXECUTOR: Executor = ThreadPoolExecutor(
    max_workers=8,
    thread_name_prefix="tool-runner",
)


def run_with_guard(
    spec: ToolSpec,
    arguments: object,
    *,
    idempotency_key: str | None = None,
    store: IdempotencyStore | None = None,
    policy: RetryPolicy | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> ToolResult:
    """带超时、重试与幂等保护地执行一次工具调用。"""
    active_policy = policy or RetryPolicy()
    active_store = store or DEFAULT_IDEMPOTENCY_STORE
    requires_idempotency = spec.risk_level == "write"

    if requires_idempotency:
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            return ToolResult.failure(
                ErrorType.MISSING_IDEMPOTENCY_KEY,
                f"{spec.name} 会修改业务数据，必须携带幂等键",
            )

        cached = active_store.lookup(idempotency_key)
        if cached is not None:
            return cached

        if not active_store.claim(idempotency_key):
            return ToolResult.failure(
                ErrorType.DUPLICATE_REQUEST,
                f"{spec.name} 的同一请求正在处理中，请勿重复提交",
                execution_state=ExecutionState.UNKNOWN,
            )

    # 参数不合法时不能占用幂等键：那不是一个有效的业务请求。
    issues = validate_arguments(spec.parameters, arguments)
    if issues:
        if requires_idempotency and idempotency_key:
            active_store.release(idempotency_key)
        detail = "；".join(issue.describe() for issue in issues)
        return ToolResult.failure(ErrorType.INVALID_ARGUMENTS, detail)

    try:
        result = _execute_with_retry(spec, arguments, active_policy, sleep_fn)
    except BaseException:
        if requires_idempotency and idempotency_key:
            active_store.release(idempotency_key)
        raise

    if requires_idempotency and idempotency_key:
        # 失败结果同样要记录：否则重复提交会再次执行，幂等就失效了。
        active_store.store(idempotency_key, result)

    return result


def _execute_with_retry(
    spec: ToolSpec,
    arguments: object,
    policy: RetryPolicy,
    sleep_fn: Callable[[float], None],
) -> ToolResult:
    started = time.monotonic()
    attempt = 0

    while True:
        attempt += 1
        result = _execute_once(spec, arguments)

        elapsed = time.monotonic() - started
        if not _should_retry(result, attempt, policy, elapsed):
            return result

        sleep_fn(_backoff_delay(policy, attempt))


def _execute_once(spec: ToolSpec, arguments: object) -> ToolResult:
    # 线程池不会自动继承 ContextVar，必须在提交前捕获当前上下文，
    # 否则 handler 在工作线程里读不到请求身份。
    captured = capture_for_thread()
    future = _EXECUTOR.submit(captured.run, run_tool, spec, arguments)

    try:
        return future.result(timeout=spec.timeout_seconds)
    except FuturesTimeoutError:
        # cancel 只能作用于尚未开始的任务：已经在跑的函数不会因此停止。
        future.cancel()
        retryable = spec.risk_level == "read" and spec.retryable_on_timeout
        return ToolResult.failure(
            ErrorType.TIMEOUT,
            f"{spec.name} 在 {spec.timeout_seconds} 秒内未返回结果",
            retryable=retryable,
            execution_state=_timeout_execution_state(spec),
        )
    except Exception:
        # 内部异常只进日志，对外返回不含堆栈的安全信息。
        return ToolResult.failure(
            ErrorType.INTERNAL_ERROR,
            "工具执行时发生内部错误",
        )


def _timeout_execution_state(spec: ToolSpec) -> ExecutionState:
    if spec.risk_level == "write":
        # 写入请求可能已经在服务端生效，只是响应没有回来。
        return ExecutionState.UNKNOWN
    # 只读调用没有可观察的副作用，按未生效处理，以便允许重试。
    return ExecutionState.NOT_EXECUTED


def _should_retry(
    result: ToolResult,
    attempt: int,
    policy: RetryPolicy,
    elapsed: float,
) -> bool:
    if result.status != "error" or result.error is None:
        return False
    if not result.error.retryable:
        return False
    if attempt >= policy.max_attempts:
        return False
    return elapsed < policy.total_budget_seconds


def _backoff_delay(policy: RetryPolicy, attempt: int) -> float:
    delay = policy.base_delay_seconds * (2 ** (attempt - 1))
    return min(delay, policy.max_delay_seconds)