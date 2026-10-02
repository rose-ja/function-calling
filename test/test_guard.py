import time
import unittest

from guard import IdempotencyStore, RetryPolicy, run_with_guard
from tool_core import ErrorType, ExecutionState, ToolResult
from tool_spec import ToolSpec


EMPTY_PARAMETERS: dict[str, object] = {
    "type": "object",
    "properties": {},
    "required": [],
    "additionalProperties": False,
}


def build_read_spec(
    handler,
    *,
    name: str = "slow_read",
    timeout_seconds: float = 0.05,
    retryable_on_timeout: bool = True,
) -> ToolSpec:
    return ToolSpec(
        name=name,
        description="测试用的只读工具",
        parameters=EMPTY_PARAMETERS,
        handler=handler,
        risk_level="read",
        timeout_seconds=timeout_seconds,
        retryable_on_timeout=retryable_on_timeout,
    )


def build_write_spec(
    handler,
    *,
    name: str = "slow_write",
    timeout_seconds: float = 0.05,
) -> ToolSpec:
    return ToolSpec(
        name=name,
        description="测试用的写入工具",
        parameters=EMPTY_PARAMETERS,
        handler=handler,
        risk_level="write",
        requires_confirmation=False,
        timeout_seconds=timeout_seconds,
    )


def build_policy(**overrides: object) -> RetryPolicy:
    base: dict[str, object] = {
        "max_attempts": 3,
        "base_delay_seconds": 0.2,
        "max_delay_seconds": 2.0,
        "total_budget_seconds": 5.0,
    }
    base.update(overrides)
    return RetryPolicy(**base)  # type: ignore[arg-type]


class TimeoutTests(unittest.TestCase):
    def test_slow_handler_times_out(self) -> None:
        spec = build_read_spec(lambda arguments: (time.sleep(0.3),)[1])

        result = run_with_guard(spec, {})

        self.assertEqual(result.status, "error")
        self.assertEqual(result.error.type, ErrorType.TIMEOUT)

    def test_read_timeout_is_retried_until_it_succeeds(self) -> None:
        calls: list[int] = []

        def handler(arguments: dict[str, object]) -> ToolResult:
            calls.append(1)
            if len(calls) == 1:
                time.sleep(0.3)
            return ToolResult.success({"attempt": len(calls)})

        spec = build_read_spec(handler)

        result = run_with_guard(spec, {}, sleep_fn=lambda seconds: None)

        self.assertEqual(result.status, "success")
        self.assertEqual(result.data["attempt"], 2)
        self.assertEqual(len(calls), 2)

    def test_read_timeout_exhausts_attempts(self) -> None:
        sleeps: list[float] = []

        def handler(arguments: dict[str, object]) -> ToolResult:
            time.sleep(0.3)
            return ToolResult.success({})

        spec = build_read_spec(handler)

        result = run_with_guard(
            spec,
            {},
            policy=build_policy(max_attempts=2),
            sleep_fn=sleeps.append,
        )

        self.assertEqual(result.error.type, ErrorType.TIMEOUT)
        self.assertEqual(result.error.execution_state, ExecutionState.NOT_EXECUTED)
        self.assertEqual(len(sleeps), 1)

    def test_read_tool_without_retryable_timeout_does_not_retry(self) -> None:
        calls: list[int] = []

        def handler(arguments: dict[str, object]) -> ToolResult:
            calls.append(1)
            time.sleep(0.3)
            return ToolResult.success({})

        spec = build_read_spec(handler, retryable_on_timeout=False)

        result = run_with_guard(spec, {}, sleep_fn=lambda seconds: None)

        self.assertEqual(result.error.type, ErrorType.TIMEOUT)
        self.assertFalse(result.error.retryable)
        self.assertEqual(len(calls), 1)

    def test_write_timeout_is_not_retried_and_state_is_unknown(self) -> None:
        calls: list[int] = []

        def handler(arguments: dict[str, object]) -> ToolResult:
            calls.append(1)
            time.sleep(0.3)
            return ToolResult.success({})

        spec = build_write_spec(handler)

        result = run_with_guard(
            spec,
            {},
            idempotency_key="session-1:slow_write:request-1",
            store=IdempotencyStore(),
            sleep_fn=lambda seconds: None,
        )

        self.assertEqual(result.error.type, ErrorType.TIMEOUT)
        self.assertFalse(result.error.retryable)
        self.assertEqual(result.error.execution_state, ExecutionState.UNKNOWN)
        self.assertEqual(len(calls), 1)


class RetryTests(unittest.TestCase):
    def test_retryable_error_is_retried(self) -> None:
        calls: list[int] = []

        def handler(arguments: dict[str, object]) -> ToolResult:
            calls.append(1)
            if len(calls) < 3:
                return ToolResult.failure(
                    ErrorType.UPSTREAM_UNAVAILABLE,
                    "上游服务暂时不可用",
                    retryable=True,
                )
            return ToolResult.success({"attempt": len(calls)})

        spec = build_read_spec(handler)

        result = run_with_guard(spec, {}, sleep_fn=lambda seconds: None)

        self.assertEqual(result.status, "success")
        self.assertEqual(result.data["attempt"], 3)

    def test_non_retryable_error_is_not_retried(self) -> None:
        calls: list[int] = []

        def handler(arguments: dict[str, object]) -> ToolResult:
            calls.append(1)
            return ToolResult.failure(ErrorType.CITY_NOT_SUPPORTED, "不支持")

        spec = build_read_spec(handler)

        result = run_with_guard(spec, {}, sleep_fn=lambda seconds: None)

        self.assertEqual(result.error.type, ErrorType.CITY_NOT_SUPPORTED)
        self.assertEqual(len(calls), 1)

    def test_internal_error_is_not_retried(self) -> None:
        calls: list[int] = []

        def handler(arguments: dict[str, object]) -> ToolResult:
            calls.append(1)
            raise RuntimeError("内部故障")

        spec = build_read_spec(handler)

        result = run_with_guard(spec, {}, sleep_fn=lambda seconds: None)

        self.assertEqual(result.error.type, ErrorType.INTERNAL_ERROR)
        self.assertEqual(len(calls), 1)

    def test_backoff_delay_grows_exponentially(self) -> None:
        sleeps: list[float] = []

        def handler(arguments: dict[str, object]) -> ToolResult:
            return ToolResult.failure(
                ErrorType.UPSTREAM_UNAVAILABLE,
                "上游服务暂时不可用",
                retryable=True,
            )

        spec = build_read_spec(handler)

        result = run_with_guard(
            spec,
            {},
            policy=build_policy(max_attempts=3),
            sleep_fn=sleeps.append,
        )

        self.assertEqual(result.status, "error")
        self.assertEqual([round(delay, 3) for delay in sleeps], [0.2, 0.4])

    def test_backoff_delay_is_capped(self) -> None:
        sleeps: list[float] = []

        def handler(arguments: dict[str, object]) -> ToolResult:
            return ToolResult.failure(
                ErrorType.UPSTREAM_UNAVAILABLE,
                "上游服务暂时不可用",
                retryable=True,
            )

        spec = build_read_spec(handler)

        run_with_guard(
            spec,
            {},
            policy=build_policy(max_attempts=4, max_delay_seconds=0.5),
            sleep_fn=sleeps.append,
        )

        self.assertEqual([round(delay, 3) for delay in sleeps], [0.2, 0.4, 0.5])


class IdempotencyTests(unittest.TestCase):
    def test_write_tool_requires_an_idempotency_key(self) -> None:
        spec = build_write_spec(lambda arguments: ToolResult.success({}))

        result = run_with_guard(spec, {}, store=IdempotencyStore())

        self.assertEqual(result.error.type, ErrorType.MISSING_IDEMPOTENCY_KEY)

    def test_read_tool_needs_no_idempotency_key(self) -> None:
        spec = build_read_spec(lambda arguments: ToolResult.success({"ok": True}))

        result = run_with_guard(spec, {})

        self.assertEqual(result.status, "success")

    def test_same_key_executes_handler_only_once(self) -> None:
        calls: list[int] = []

        def handler(arguments: dict[str, object]) -> ToolResult:
            calls.append(1)
            return ToolResult.success({"todo_id": f"todo-{len(calls):03d}"})

        spec = build_write_spec(handler)
        store = IdempotencyStore()
        key = "session-1:create_todo:request-7"

        first = run_with_guard(spec, {}, idempotency_key=key, store=store)
        second = run_with_guard(spec, {}, idempotency_key=key, store=store)

        self.assertEqual(len(calls), 1)
        self.assertEqual(first.data, second.data)

    def test_different_keys_execute_twice(self) -> None:
        calls: list[int] = []

        def handler(arguments: dict[str, object]) -> ToolResult:
            calls.append(1)
            return ToolResult.success({"todo_id": f"todo-{len(calls):03d}"})

        spec = build_write_spec(handler)
        store = IdempotencyStore()

        run_with_guard(spec, {}, idempotency_key="request-1", store=store)
        run_with_guard(spec, {}, idempotency_key="request-2", store=store)

        self.assertEqual(len(calls), 2)

    def test_failed_write_is_recorded_so_replay_does_not_reexecute(self) -> None:
        calls: list[int] = []

        def handler(arguments: dict[str, object]) -> ToolResult:
            calls.append(1)
            return ToolResult.failure(ErrorType.INVALID_TIME_RANGE, "时间范围不合法")

        spec = build_write_spec(handler)
        store = IdempotencyStore()
        key = "session-1:create_todo:request-8"

        first = run_with_guard(spec, {}, idempotency_key=key, store=store)
        second = run_with_guard(spec, {}, idempotency_key=key, store=store)

        self.assertEqual(len(calls), 1)
        self.assertEqual(first.error.type, second.error.type)

    def test_invalid_arguments_do_not_burn_the_key(self) -> None:
        calls: list[int] = []

        def handler(arguments: dict[str, object]) -> ToolResult:
            calls.append(1)
            return ToolResult.success({"ok": True})

        spec = ToolSpec(
            name="create_todo",
            description="需要 city 字段的测试用写入工具",
            parameters={
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
                "additionalProperties": False,
            },
            handler=handler,
            risk_level="write",
            requires_confirmation=False,
        )
        store = IdempotencyStore()
        key = "session-1:create_todo:request-9"

        rejected = run_with_guard(spec, {}, idempotency_key=key, store=store)
        accepted = run_with_guard(
            spec, {"city": "北京"}, idempotency_key=key, store=store
        )

        self.assertEqual(rejected.error.type, ErrorType.INVALID_ARGUMENTS)
        self.assertEqual(accepted.status, "success")
        self.assertEqual(len(calls), 1)

    def test_concurrent_duplicate_request_is_rejected(self) -> None:
        spec = build_write_spec(lambda arguments: ToolResult.success({}))
        store = IdempotencyStore()
        key = "session-1:create_todo:request-10"

        # 模拟另一个并发请求已经抢到了同一个键的执行权。
        self.assertTrue(store.claim(key))

        result = run_with_guard(spec, {}, idempotency_key=key, store=store)

        self.assertEqual(result.error.type, ErrorType.DUPLICATE_REQUEST)
        self.assertEqual(result.error.execution_state, ExecutionState.UNKNOWN)

    def test_unknown_state_timeout_is_replayed_as_is(self) -> None:
        spec = build_write_spec(lambda arguments: (time.sleep(0.3),)[1])
        store = IdempotencyStore()
        key = "session-1:slow_write:request-11"

        first = run_with_guard(spec, {}, idempotency_key=key, store=store)
        second = run_with_guard(spec, {}, idempotency_key=key, store=store)

        self.assertEqual(first.error.type, ErrorType.TIMEOUT)
        self.assertEqual(second.error.type, ErrorType.TIMEOUT)
        self.assertEqual(second.error.execution_state, ExecutionState.UNKNOWN)


class RetryPolicyTests(unittest.TestCase):
    def test_zero_attempts_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            build_policy(max_attempts=0)

    def test_negative_delay_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            build_policy(base_delay_seconds=-1)

    def test_max_delay_below_base_delay_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            build_policy(base_delay_seconds=1.0, max_delay_seconds=0.5)


if __name__ == "__main__":
    unittest.main()
