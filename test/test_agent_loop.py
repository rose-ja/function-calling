import unittest
from datetime import date, timedelta

from agent_loop import (
    AgentBudget,
    ModelOutputExhausted,
    ModelTurn,
    ScriptedModel,
    ToolCall,
    derive_idempotency_key,
    run_agent,
    serialize_result,
)
from guard import DEFAULT_IDEMPOTENCY_STORE
from request_context import RequestContext, use_context
from todo_tool import execute_list_todos, reset_todos
from tool_core import ErrorType, ExecutionState, ToolResult

TOMORROW = (date.today() + timedelta(days=1)).isoformat()


def call(tool_name: str, **arguments: object) -> ModelTurn:
    return ModelTurn(tool_call=ToolCall(tool_name, dict(arguments)))


def answer(text: str) -> ModelTurn:
    return ModelTurn(final_answer=text)


def context() -> RequestContext:
    return RequestContext(actor_id="user-42", session_id="session-a")


def list_titles(run_context: RequestContext) -> list[str]:
    with use_context(run_context):
        listing = execute_list_todos({})
    return [item["title"] for item in listing.data["items"]]


class AgentLoopTestBase(unittest.TestCase):
    def setUp(self) -> None:
        reset_todos()
        DEFAULT_IDEMPOTENCY_STORE.clear()


class ModelTurnTests(unittest.TestCase):
    def test_turn_requires_exactly_one_output(self) -> None:
        with self.assertRaises(ValueError):
            ModelTurn()
        with self.assertRaises(ValueError):
            ModelTurn(
                tool_call=ToolCall("get_weather", {"city": "北京"}),
                final_answer="北京下雨",
            )

    def test_script_requires_at_least_one_turn(self) -> None:
        with self.assertRaises(ValueError):
            ScriptedModel([])


class BudgetTests(unittest.TestCase):
    def test_zero_rounds_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            AgentBudget(max_rounds=0)

    def test_boolean_budget_is_rejected(self) -> None:
        with self.assertRaises(TypeError):
            AgentBudget(max_rounds=True)


class HappyPathTests(AgentLoopTestBase):
    def test_completes_with_final_answer(self) -> None:
        model = ScriptedModel(
            [
                call("get_weather", city="北京"),
                answer("北京今天下雨，记得带伞。"),
            ]
        )

        run = run_agent("北京今天下雨吗", model, context=context())

        self.assertEqual(run.status, "completed")
        self.assertEqual(run.answer, "北京今天下雨，记得带伞。")
        self.assertIsNone(run.stop_reason)
        self.assertEqual(run.tool_calls, 1)

    def test_model_sees_the_tool_result_in_history(self) -> None:
        model = ScriptedModel(
            [call("get_weather", city="北京"), answer("下雨")]
        )

        run = run_agent("北京今天下雨吗", model, context=context())

        second_history = model.seen_histories[1]
        tool_entry = second_history[-1]

        self.assertEqual(tool_entry["role"], "tool")
        self.assertEqual(tool_entry["tool_name"], "get_weather")
        self.assertEqual(tool_entry["result"]["status"], "success")
        self.assertEqual(tool_entry["result"]["data"]["condition"], "rain")
        self.assertEqual(run.tool_calls, 1)

    def test_steps_record_every_call_for_audit(self) -> None:
        model = ScriptedModel(
            [
                call("search", query="空调", limit=1),
                call("get_weather", city="上海"),
                answer("完成"),
            ]
        )

        run = run_agent("查一下", model, context=context())

        self.assertEqual(
            [(step.round_index, step.call.tool_name) for step in run.steps],
            [(1, "search"), (2, "get_weather")],
        )


class CorrectionTests(AgentLoopTestBase):
    def test_unknown_tool_is_correctable(self) -> None:
        model = ScriptedModel(
            [
                call("search_weather", city="北京"),
                call("get_weather", city="北京"),
                answer("北京今天下雨。"),
            ]
        )

        run = run_agent("北京今天下雨吗", model, context=context())

        self.assertEqual(run.status, "completed")
        self.assertEqual(
            run.steps[0].result.error.type, ErrorType.UNKNOWN_TOOL
        )

    def test_unknown_tool_feedback_lists_available_tools(self) -> None:
        model = ScriptedModel(
            [call("search_weather", city="北京"), answer("放弃")]
        )

        run_agent("北京今天下雨吗", model, context=context())

        feedback = model.seen_histories[1][-1]["result"]

        self.assertIn("available_tools", feedback)
        # 提示里只出现注册表里真实存在的工具名，且不含内部未授权工具。
        self.assertEqual(
            feedback["available_tools"],
            sorted(["get_weather", "get_exchange_rate", "search", "list_todos", "create_todo"]),
        )

    def test_invalid_arguments_are_correctable(self) -> None:
        model = ScriptedModel(
            [
                call("get_weather", city=""),
                call("get_weather", city="北京"),
                answer("北京今天下雨。"),
            ]
        )

        run = run_agent("北京今天下雨吗", model, context=context())

        self.assertEqual(run.status, "completed")
        self.assertEqual(
            run.steps[0].result.error.type, ErrorType.INVALID_ARGUMENTS
        )

    def test_missing_required_field_is_correctable(self) -> None:
        model = ScriptedModel(
            [
                call("get_weather"),
                call("get_weather", city="北京"),
                answer("下雨"),
            ]
        )

        run = run_agent("北京今天下雨吗", model, context=context())

        self.assertEqual(run.status, "completed")

    def test_correction_limit_stops_the_loop(self) -> None:
        model = ScriptedModel(
            [
                call("get_weather", city=""),
                call("get_weather", city=""),
                call("get_weather", city=""),
                call("get_weather", city="北京"),
                answer("下雨"),
            ]
        )

        run = run_agent(
            "北京今天下雨吗",
            model,
            context=context(),
            budget=AgentBudget(max_corrections=2),
        )

        self.assertEqual(run.status, "stopped")
        self.assertEqual(run.stop_reason, "CORRECTION_LIMIT")

    def test_business_error_is_not_counted_as_correction(self) -> None:
        model = ScriptedModel(
            [
                call("get_weather", city="广州"),
                call("get_weather", city="广州"),
                call("get_weather", city="广州"),
                answer("暂时查不到这个城市。"),
            ]
        )

        run = run_agent(
            "广州今天下雨吗",
            model,
            context=context(),
            budget=AgentBudget(max_corrections=1),
        )

        self.assertEqual(run.status, "completed")
        self.assertEqual(
            [step.result.error.type for step in run.steps],
            [ErrorType.CITY_NOT_SUPPORTED] * 3,
        )


class StopConditionTests(AgentLoopTestBase):
    def test_round_limit_stops_the_loop(self) -> None:
        model = ScriptedModel([call("get_weather", city="北京")] * 5)

        run = run_agent(
            "北京今天下雨吗",
            model,
            context=context(),
            budget=AgentBudget(max_rounds=3),
        )

        self.assertEqual(run.status, "stopped")
        self.assertEqual(run.stop_reason, "ROUND_LIMIT")
        self.assertEqual(run.tool_calls, 3)

    def test_call_limit_stops_the_loop(self) -> None:
        model = ScriptedModel([call("get_weather", city="北京")] * 5)

        run = run_agent(
            "北京今天下雨吗",
            model,
            context=context(),
            budget=AgentBudget(max_rounds=5, max_tool_calls=2),
        )

        self.assertEqual(run.stop_reason, "CALL_LIMIT")
        self.assertEqual(run.tool_calls, 2)

    def test_exhausted_model_stops_instead_of_spinning(self) -> None:
        model = ScriptedModel([call("get_weather", city="北京")])

        run = run_agent("北京今天下雨吗", model, context=context())

        self.assertEqual(run.status, "stopped")
        self.assertEqual(run.stop_reason, "MODEL_OUTPUT_EXHAUSTED")

    def test_confirmation_required_stops_the_loop(self) -> None:
        model = ScriptedModel(
            [
                call("create_todo", title="准备面试", due_date=TOMORROW),
                answer("已经帮你建好了。"),
            ]
        )

        run = run_agent("帮我建个待办", model, context=context(), confirmed=False)

        self.assertEqual(run.status, "stopped")
        self.assertEqual(run.stop_reason, "CONFIRMATION_REQUIRED")
        self.assertEqual(run.answer, None)
        # 关键断言：没有确认时，一条数据都不许落库。
        self.assertEqual(list_titles(context()), [])

    def test_model_is_not_asked_again_after_confirmation_required(self) -> None:
        model = ScriptedModel(
            [
                call("create_todo", title="准备面试", due_date=TOMORROW),
                answer("已经帮你建好了。"),
            ]
        )

        run_agent("帮我建个待办", model, context=context(), confirmed=False)

        # 只调用了 1 次模型：确认类中断直接交回用户，不继续空转。
        self.assertEqual(len(model.seen_histories), 1)


class WriteThroughLoopTests(AgentLoopTestBase):
    def test_confirmed_write_creates_one_todo(self) -> None:
        model = ScriptedModel(
            [
                call("create_todo", title="准备面试", due_date=TOMORROW),
                answer("待办已创建。"),
            ]
        )

        run = run_agent("帮我建个待办", model, context=context(), confirmed=True)

        self.assertEqual(run.status, "completed")
        self.assertEqual(list_titles(context()), ["准备面试"])

    def test_identical_repeated_write_is_deduplicated(self) -> None:
        model = ScriptedModel(
            [
                call("create_todo", title="准备面试", due_date=TOMORROW),
                call("create_todo", title="准备面试", due_date=TOMORROW),
                answer("待办已创建。"),
            ]
        )

        run = run_agent("帮我建个待办", model, context=context(), confirmed=True)

        self.assertEqual(run.status, "completed")
        # 参数指纹相同 → 幂等键相同 → 第二次直接回放，只落一条数据。
        self.assertEqual(list_titles(context()), ["准备面试"])

    def test_different_arguments_are_different_requests(self) -> None:
        model = ScriptedModel(
            [
                call("create_todo", title="准备面试", due_date=TOMORROW),
                call("create_todo", title="复习计网", due_date=TOMORROW),
                answer("两个待办都建好了。"),
            ]
        )

        run = run_agent("帮我建两个待办", model, context=context(), confirmed=True)

        self.assertEqual(run.status, "completed")
        self.assertEqual(list_titles(context()), ["准备面试", "复习计网"])

    def test_write_failure_does_not_break_the_loop(self) -> None:
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        model = ScriptedModel(
            [
                call("create_todo", title="准备面试", due_date=yesterday),
                answer("那个日期已经过去了，换个日期吧。"),
            ]
        )

        run = run_agent("帮我建个待办", model, context=context(), confirmed=True)

        self.assertEqual(run.status, "completed")
        self.assertEqual(
            run.steps[0].result.error.type, ErrorType.INVALID_TIME_RANGE
        )
        self.assertEqual(list_titles(context()), [])


class IdentityTests(AgentLoopTestBase):
    def test_identity_is_available_inside_the_loop(self) -> None:
        model = ScriptedModel(
            [call("list_todos"), answer("你还没有待办。")]
        )

        run = run_agent("我有哪些待办", model, context=context())

        self.assertEqual(run.status, "completed")
        self.assertEqual(run.steps[0].result.data["owner_id"], "user-42")

    def test_idempotency_key_is_scoped_to_session(self) -> None:
        key_a = derive_idempotency_key(context(), "create_todo", {"title": "A"})
        key_b = derive_idempotency_key(
            RequestContext(actor_id="user-42", session_id="session-b"),
            "create_todo",
            {"title": "A"},
        )

        self.assertNotEqual(key_a, key_b)

    def test_different_arguments_produce_different_keys(self) -> None:
        first = derive_idempotency_key(context(), "create_todo", {"title": "A"})
        second = derive_idempotency_key(context(), "create_todo", {"title": "B"})

        self.assertNotEqual(first, second)

    def test_argument_order_does_not_change_the_key(self) -> None:
        first = derive_idempotency_key(
            context(), "create_todo", {"title": "A", "due_date": TOMORROW}
        )
        second = derive_idempotency_key(
            context(), "create_todo", {"due_date": TOMORROW, "title": "A"}
        )

        self.assertEqual(first, second)


class SerializationTests(unittest.TestCase):
    def test_success_payload_contains_only_data(self) -> None:
        payload = serialize_result(ToolResult.success({"city": "北京"}))

        self.assertEqual(payload, {"status": "success", "data": {"city": "北京"}})

    def test_error_payload_contains_actionable_fields(self) -> None:
        payload = serialize_result(
            ToolResult.failure(
                ErrorType.TIMEOUT,
                "超时了",
                retryable=False,
                execution_state=ExecutionState.UNKNOWN,
            )
        )

        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["error_type"], "TIMEOUT")
        self.assertEqual(payload["execution_state"], "unknown")
        self.assertFalse(payload["retryable"])

    def test_error_payload_hides_internal_details(self) -> None:
        payload = serialize_result(
            ToolResult.failure(ErrorType.INTERNAL_ERROR, "工具执行时发生内部错误")
        )

        self.assertNotIn("traceback", json_dumps_lower(payload))
        self.assertNotIn("postgres", json_dumps_lower(payload))
        self.assertNotIn("stack", json_dumps_lower(payload))


def json_dumps_lower(value: object) -> str:
    import json

    return json.dumps(value, ensure_ascii=False).lower()


if __name__ == "__main__":
    unittest.main()
