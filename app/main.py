from __future__ import annotations

import json
from datetime import date, timedelta

from dispatcher import TOOL_REGISTRY, dispatch_tool
from guard import IdempotencyStore, run_with_guard
from request_context import RequestContext, use_context
from todo_tool import reset_todos
from tool_core import ToolResult
from tool_spec import ToolSpec


def main() -> None:
    for spec in TOOL_REGISTRY.values():
        print(
            f"{spec.name:<18} risk={spec.risk_level} "
            f"timeout={spec.timeout_seconds}s "
            f"retry_on_timeout={spec.retryable_on_timeout}"
        )

    print("\n--- 提供给模型的工具契约 ---")
    print(
        json.dumps(
            [spec.to_model_schema() for spec in TOOL_REGISTRY.values()],
            ensure_ascii=False,
            indent=2,
        )
    )

    print("\n--- 模拟模型提出的调用（不可信输入）---")
    raw_model_outputs = [
        {"tool_name": "get_weather", "arguments": {"city": "北京"}},
        {"tool_name": "get_weather", "arguments": {"city": ""}},
        {
            "tool_name": "get_exchange_rate",
            "arguments": {"base_currency": "CNY", "quote_currency": "EUR"},
        },
        {
            "tool_name": "get_exchange_rate",
            "arguments": {"base_currency": "cny", "quote_currency": "USD"},
        },
        {"tool_name": "search", "arguments": {"query": "空调"}},
        {"tool_name": "search", "arguments": {"query": "维修", "limit": 1}},
        {"tool_name": "search", "arguments": {"query": "sla", "scope": "docs"}},
        {"tool_name": "search", "arguments": {"query": "不存在的关键词"}},
        {"tool_name": "search", "arguments": {"query": "工单", "scope": "users"}},
        {"tool_name": "search", "arguments": {"query": "工单", "limit": True}},
        {"tool_name": "search_weather", "arguments": {"city": "北京"}},
    ]

    for model_output in raw_model_outputs:
        result = dispatch_tool(
            model_output["tool_name"],
            model_output["arguments"],
        )
        label = model_output["tool_name"]
        if result.status == "success":
            summary = _summarize(result.data)
            print(f"OK    {label:<18} {summary}")
        else:
            print(
                f"FAIL  {result.error.type.value:<24} "
                f"{result.error.execution_state.value:<12} {result.error.message}"
            )

    _demo_guard()
    _demo_todo()
    print()


def _demo_guard() -> None:
    """演示超时、重试与幂等：写入工具必须带幂等键，且同键只执行一次。"""
    print("\n--- 治理层演示 ---")

    executions: list[int] = []

    def create_todo(arguments: dict[str, object]) -> ToolResult:
        executions.append(1)
        return ToolResult.success({"todo_id": f"todo-{len(executions):03d}"})

    spec = ToolSpec(
        name="create_todo",
        description="演示用的写入工具",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        handler=create_todo,
        risk_level="write",
    )

    store = IdempotencyStore()
    key = "session-1:create_todo:request-7"

    without_key = run_with_guard(spec, {}, store=store)
    print(f"不带幂等键：{without_key.error.type.value}")

    first = run_with_guard(spec, {}, idempotency_key=key, store=store)
    second = run_with_guard(spec, {}, idempotency_key=key, store=store)
    third = run_with_guard(spec, {}, idempotency_key="request-8", store=store)

    print(f"第一次调用：{first.data}")
    print(f"同键重复调用：{second.data}")
    print(f"换一个新键：{third.data}")
    print(f"handler 实际执行次数：{len(executions)}（3 次调用只执行了 2 次）")


def _demo_todo() -> None:
    """演示真实写入工具：身份来自会话、需要确认、需要幂等键。"""
    print("\n--- 待办工具演示 ---")

    reset_todos()
    context = RequestContext(actor_id="user-42", session_id="session-a")
    tomorrow = (date.today() + timedelta(days=1)).isoformat()

    def key(request_id: str) -> str:
        return context.idempotency_key("create_todo", request_id)

    with use_context(context):
        print(f"查询空列表：{dispatch_tool('list_todos', {}).data}")

        blocked = dispatch_tool(
            "create_todo", {"title": "准备面试", "due_date": tomorrow}
        )
        print(f"未确认：{blocked.error.type.value}")

        no_key = dispatch_tool(
            "create_todo",
            {"title": "准备面试", "due_date": tomorrow},
            confirmed=True,
        )
        print(f"已确认但无幂等键：{no_key.error.type.value}")

        first = dispatch_tool(
            "create_todo",
            {"title": "准备面试", "due_date": tomorrow},
            confirmed=True,
            idempotency_key=key("req-1"),
        )
        print(f"创建成功：{first.data}")

        replay = dispatch_tool(
            "create_todo",
            {"title": "准备面试", "due_date": tomorrow},
            confirmed=True,
            idempotency_key=key("req-1"),
        )
        print(f"同键重放（返回同一结果）：{replay.data == first.data}")

        duplicate = dispatch_tool(
            "create_todo",
            {"title": "准备面试", "due_date": tomorrow},
            confirmed=True,
            idempotency_key=key("req-2"),
        )
        print(f"换新键但内容相同（业务去重）：{duplicate.error.type.value}")

        forged = dispatch_tool(
            "create_todo",
            {"title": "别人的待办", "due_date": tomorrow, "owner_id": "user-999"},
            confirmed=True,
            idempotency_key=key("req-3"),
        )
        print(f"模型伪造 owner_id：{forged.error.type.value}（{forged.error.message}）")

        listing = dispatch_tool("list_todos", {})
        print(f"最终列表：{listing.data}")


def _summarize(data: dict[str, object]) -> str:
    """结果里可能带 items 这样的长列表，打印时压缩成摘要。"""
    if "items" not in data:
        return str(data)

    items = data["items"]
    count = len(items) if isinstance(items, list) else 0
    return (
        f"query={data['query']!r} scope={data['scope']} "
        f"items={count} total_matched={data['total_matched']} "
        f"truncated={data['truncated']}"
    )


if __name__ == "__main__":
    main()