"""按场景演示 guard.py 的四个职责：超时、重试、幂等、执行状态。

运行：
    python trace_guard.py

这个脚本只做演示，不参与测试。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT / "app"))

from guard import IdempotencyStore, RetryPolicy, run_with_guard  # noqa: E402
from tool_core import ErrorType, ExecutionState, ToolResult  # noqa: E402
from tool_spec import ToolSpec  # noqa: E402


EMPTY_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "required": [],
    "additionalProperties": False,
}


def build_write_spec(
    handler,
    *,
    name: str = "create_todo",
    timeout_seconds: float = 0.05,
) -> ToolSpec:
    return ToolSpec(
        name=name,
        description="演示用写入工具",
        parameters=EMPTY_PARAMETERS,
        handler=handler,
        risk_level="write",
        timeout_seconds=timeout_seconds,
    )


def build_read_spec(
    handler,
    *,
    name: str = "slow_query",
    timeout_seconds: float = 0.05,
    retryable_on_timeout: bool = True,
) -> ToolSpec:
    return ToolSpec(
        name=name,
        description="演示用只读工具",
        parameters=EMPTY_PARAMETERS,
        handler=handler,
        risk_level="read",
        timeout_seconds=timeout_seconds,
        retryable_on_timeout=retryable_on_timeout,
    )


def section(title: str) -> None:
    print()
    print("=" * 68)
    print(title)
    print("=" * 68)


def scenario_1_no_guard() -> None:
    section("场景 1：没有治理，用户连点两次确认")

    created: list[str] = []

    def handler(arguments: dict[str, Any]) -> ToolResult:
        created.append(f"todo-{len(created) + 1:03d}")
        return ToolResult.success({"todo_id": created[-1]})

    # 直接调用 handler：没有分发、没有幂等、没有任何记录。
    handler({})
    handler({})

    print(f"用户点了 2 次，产生的待办：{created}")
    print("问题：同一个业务意图，产生了 2 条数据。")


def scenario_2_with_idempotency() -> None:
    section("场景 2：加上 guard + 同一个幂等键")

    created: list[str] = []

    def handler(arguments: dict[str, Any]) -> ToolResult:
        created.append(f"todo-{len(created) + 1:03d}")
        return ToolResult.success({"todo_id": created[-1]})

    spec = build_write_spec(handler)
    store = IdempotencyStore()
    key = "session-1:create_todo:request-7"

    for index in (1, 2, 3):
        result = run_with_guard(spec, {}, idempotency_key=key, store=store)
        print(f"第 {index} 次调用 → {result.data}")

    print(f"实际创建的待办：{created}（只有 1 条）")
    print("说明：第 2、3 次直接返回台账里的结果，handler 没有被调用。")


def scenario_3_different_keys() -> None:
    section("场景 3：换成不同的幂等键，就是两次不同的业务请求")

    created: list[str] = []

    def handler(arguments: dict[str, Any]) -> ToolResult:
        created.append(f"todo-{len(created) + 1:03d}")
        return ToolResult.success({"todo_id": created[-1]})

    spec = build_write_spec(handler)
    store = IdempotencyStore()

    first = run_with_guard(spec, {}, idempotency_key="request-1", store=store)
    second = run_with_guard(spec, {}, idempotency_key="request-2", store=store)

    print(f"键 request-1 → {first.data}")
    print(f"键 request-2 → {second.data}")
    print(f"实际创建的待办：{created}")
    print("说明：键不同 = 业务意图不同，就应该产生两次效果。")


def scenario_4_concurrent() -> None:
    section("场景 4：同一个键的并发请求")

    executed: list[int] = []

    def handler(arguments: dict[str, Any]) -> ToolResult:
        executed.append(1)
        return ToolResult.success({"todo_id": "todo-001"})

    spec = build_write_spec(handler)
    store = IdempotencyStore()
    key = "session-1:create_todo:request-8"

    # 模拟另一个并发请求已经抢到了这个键的牌子，但还没执行完。
    store.claim(key)
    print("另一个并发请求已经拿到该键的执行权（尚未完成）")

    result = run_with_guard(spec, {}, idempotency_key=key, store=store)

    print(f"本次调用的结果：{result.error.type.value}")
    print(f"执行状态：{result.error.execution_state.value}")
    print(f"handler 实际执行次数：{len(executed)}")


def scenario_5_read_timeout_retry() -> None:
    section("场景 5：只读工具超时 → 允许有限重试")

    attempts: list[int] = []

    def handler(arguments: dict[str, Any]) -> ToolResult:
        attempts.append(len(attempts) + 1)
        if len(attempts) == 1:
            time.sleep(0.3)  # 第一次故意卡住，触发超时
        return ToolResult.success({"attempt": len(attempts)})

    spec = build_read_spec(handler)
    policy = RetryPolicy(
        max_attempts=3,
        base_delay_seconds=0.1,
        max_delay_seconds=0.4,
    )

    def sleep_and_log(seconds: float) -> None:
        print(f"    退避等待 {seconds:.2f}s 后重试")
        time.sleep(seconds)

    print("第 1 次尝试会超时（handler 卡住 0.3s，超时阈值 0.05s）")
    result = run_with_guard(spec, {}, policy=policy, sleep_fn=sleep_and_log)

    print(f"最终结果：{result.status} {result.data}")
    print(f"handler 被提交了 {len(attempts)} 次")


def scenario_6_write_timeout_unknown() -> None:
    section("场景 6：写入工具超时 → 不重试，且状态未知")

    attempts: list[int] = []

    def handler(arguments: dict[str, Any]) -> ToolResult:
        attempts.append(1)
        time.sleep(0.3)
        return ToolResult.success({"todo_id": "todo-001"})

    spec = build_write_spec(handler)
    store = IdempotencyStore()
    key = "session-1:create_todo:request-9"

    result = run_with_guard(spec, {}, idempotency_key=key, store=store)

    print(f"结果：{result.error.type.value}")
    print(f"是否允许重试：{result.error.retryable}")
    print(f"执行状态：{result.error.execution_state.value}")
    print(f"handler 被提交了 {len(attempts)} 次（没有重试）")

    replay = run_with_guard(spec, {}, idempotency_key=key, store=store)
    print(f"用同一个键再调一次：{replay.error.type.value}，handler 仍为 {len(attempts)} 次")


def scenario_7_missing_key() -> None:
    section("场景 7：写入工具不带幂等键")

    def handler(arguments: dict[str, Any]) -> ToolResult:
        return ToolResult.success({"todo_id": "todo-001"})

    spec = build_write_spec(handler)

    result = run_with_guard(spec, {}, store=IdempotencyStore())

    print(f"结果：{result.error.type.value}")
    print(f"说明：{result.error.message}")
    print(
        "对比一下错误码常量：",
        result.error.type is ErrorType.MISSING_IDEMPOTENCY_KEY,
        result.error.execution_state is ExecutionState.NOT_EXECUTED,
    )


def main() -> None:
    scenario_1_no_guard()
    scenario_2_with_idempotency()
    scenario_3_different_keys()
    scenario_4_concurrent()
    scenario_5_read_timeout_retry()
    scenario_6_write_timeout_unknown()
    scenario_7_missing_key()
    print()


if __name__ == "__main__":
    main()
