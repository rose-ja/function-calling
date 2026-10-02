import unittest
from datetime import date, timedelta

from dispatcher import dispatch_tool
from guard import DEFAULT_IDEMPOTENCY_STORE
from request_context import RequestContext, use_context
from todo_tool import (
    CREATE_TODO_PARAMETERS,
    CREATE_TODO_TOOL,
    LIST_TODOS_PARAMETERS,
    execute_create_todo,
    execute_list_todos,
    reset_todos,
)
from tool_core import ErrorType, ExecutionState

TODAY = date.today()
TOMORROW = (TODAY + timedelta(days=1)).isoformat()
NEXT_WEEK = (TODAY + timedelta(days=7)).isoformat()
YESTERDAY = (TODAY - timedelta(days=1)).isoformat()


def user_a() -> RequestContext:
    return RequestContext(actor_id="user-42", session_id="session-a")


def user_b() -> RequestContext:
    return RequestContext(actor_id="user-999", session_id="session-b")


class TodoTestBase(unittest.TestCase):
    def setUp(self) -> None:
        # 待办数据和幂等台账都是进程级的，必须逐条测试清空。
        reset_todos()
        DEFAULT_IDEMPOTENCY_STORE.clear()

    def create_via_dispatch(
        self,
        context: RequestContext,
        title: str,
        due_date: str,
        *,
        request_id: str,
        confirmed: bool = True,
    ):
        with use_context(context):
            return dispatch_tool(
                "create_todo",
                {"title": title, "due_date": due_date},
                confirmed=confirmed,
                idempotency_key=context.idempotency_key(
                    "create_todo", request_id
                ),
            )


class IdentityTests(TodoTestBase):
    def test_create_requires_request_identity(self) -> None:
        result = execute_create_todo({"title": "准备面试", "due_date": TOMORROW})

        self.assertEqual(result.error.type, ErrorType.IDENTITY_REQUIRED)

    def test_list_requires_request_identity(self) -> None:
        result = execute_list_todos({})

        self.assertEqual(result.error.type, ErrorType.IDENTITY_REQUIRED)

    def test_context_must_have_actor_and_session(self) -> None:
        with self.assertRaises(ValueError):
            RequestContext(actor_id="  ", session_id="session-a")
        with self.assertRaises(ValueError):
            RequestContext(actor_id="user-42", session_id="")

    def test_idempotency_key_includes_session_and_tool(self) -> None:
        key = user_a().idempotency_key("create_todo", "req-1")

        self.assertEqual(key, "session-a:create_todo:req-1")


class CreateTodoBusinessTests(TodoTestBase):
    def test_create_succeeds_and_returns_todo(self) -> None:
        with use_context(user_a()):
            result = execute_create_todo(
                {"title": "准备面试", "due_date": TOMORROW}
            )

        self.assertEqual(result.status, "success")
        self.assertTrue(result.data["created"])
        self.assertEqual(result.data["title"], "准备面试")
        self.assertEqual(result.data["due_date"], TOMORROW)
        self.assertEqual(result.data["owner_id"], "user-42")
        self.assertEqual(result.data["todo_id"], "todo-001")

    def test_title_whitespace_is_trimmed(self) -> None:
        with use_context(user_a()):
            result = execute_create_todo(
                {"title": "  准备面试  ", "due_date": TOMORROW}
            )

        self.assertEqual(result.data["title"], "准备面试")

    def test_past_due_date_is_rejected(self) -> None:
        with use_context(user_a()):
            result = execute_create_todo(
                {"title": "准备面试", "due_date": YESTERDAY}
            )

        self.assertEqual(result.error.type, ErrorType.INVALID_TIME_RANGE)
        self.assertEqual(result.error.execution_state, ExecutionState.NOT_EXECUTED)

    def test_today_is_allowed_as_due_date(self) -> None:
        with use_context(user_a()):
            result = execute_create_todo(
                {"title": "准备面试", "due_date": TODAY.isoformat()}
            )

        self.assertEqual(result.status, "success")

    def test_duplicate_todo_is_rejected_by_business_rule(self) -> None:
        with use_context(user_a()):
            first = execute_create_todo({"title": "准备面试", "due_date": TOMORROW})
            second = execute_create_todo({"title": "准备面试", "due_date": TOMORROW})

        self.assertEqual(first.status, "success")
        self.assertEqual(second.error.type, ErrorType.TODO_ALREADY_EXISTS)
        self.assertEqual(second.error.execution_state, ExecutionState.NOT_EXECUTED)

    def test_same_title_on_another_day_is_allowed(self) -> None:
        with use_context(user_a()):
            execute_create_todo({"title": "准备面试", "due_date": TOMORROW})
            second = execute_create_todo({"title": "准备面试", "due_date": NEXT_WEEK})

        self.assertEqual(second.status, "success")

    def test_different_users_may_have_the_same_todo(self) -> None:
        with use_context(user_a()):
            first = execute_create_todo({"title": "准备面试", "due_date": TOMORROW})
        with use_context(user_b()):
            second = execute_create_todo({"title": "准备面试", "due_date": TOMORROW})

        self.assertEqual(first.status, "success")
        self.assertEqual(second.status, "success")
        self.assertEqual(second.data["owner_id"], "user-999")


class ListTodoBusinessTests(TodoTestBase):
    def test_empty_list_is_still_success(self) -> None:
        with use_context(user_a()):
            result = execute_list_todos({})

        self.assertEqual(result.status, "success")
        self.assertEqual(result.data["items"], [])
        self.assertEqual(result.data["total_matched"], 0)

    def test_list_only_returns_own_todos(self) -> None:
        with use_context(user_a()):
            execute_create_todo({"title": "A 的待办", "due_date": TOMORROW})
        with use_context(user_b()):
            execute_create_todo({"title": "B 的待办", "due_date": TOMORROW})

        with use_context(user_a()):
            result = execute_list_todos({})

        self.assertEqual(
            [item["title"] for item in result.data["items"]],
            ["A 的待办"],
        )
        self.assertEqual(result.data["owner_id"], "user-42")

    def test_limit_truncates_and_marks_truncated(self) -> None:
        with use_context(user_a()):
            for index in range(3):
                execute_create_todo(
                    {"title": f"待办-{index}", "due_date": TOMORROW}
                )
            result = execute_list_todos({"limit": 2})

        self.assertEqual(len(result.data["items"]), 2)
        self.assertEqual(result.data["total_matched"], 3)
        self.assertTrue(result.data["truncated"])

    def test_returned_items_are_copies(self) -> None:
        with use_context(user_a()):
            execute_create_todo({"title": "准备面试", "due_date": TOMORROW})
            result = execute_list_todos({})

            # 外部改动返回结果，不应该影响内部数据。
            result.data["items"][0]["title"] = "被改掉了"
            again = execute_list_todos({})

        self.assertEqual(again.data["items"][0]["title"], "准备面试")


class TodoContractTests(TodoTestBase):
    """契约层：必须走 dispatch_tool，Schema 与治理策略才会参与。"""

    def test_schema_has_no_owner_field(self) -> None:
        # 归属只能来自请求身份，不能由模型指定。
        self.assertNotIn("owner_id", CREATE_TODO_PARAMETERS["properties"])
        self.assertNotIn("owner_id", LIST_TODOS_PARAMETERS["properties"])

    def test_model_supplied_owner_is_rejected(self) -> None:
        with use_context(user_a()):
            result = dispatch_tool(
                "create_todo",
                {
                    "title": "准备面试",
                    "due_date": TOMORROW,
                    "owner_id": "user-999",
                },
                confirmed=True,
                idempotency_key="session-a:create_todo:req-x",
            )

        self.assertEqual(result.error.type, ErrorType.INVALID_ARGUMENTS)
        self.assertIn("$.owner_id", result.error.message)

    def test_create_requires_confirmation(self) -> None:
        result = self.create_via_dispatch(
            user_a(), "准备面试", TOMORROW, request_id="req-1", confirmed=False
        )

        self.assertEqual(result.error.type, ErrorType.CONFIRMATION_REQUIRED)

    def test_create_requires_idempotency_key(self) -> None:
        with use_context(user_a()):
            result = dispatch_tool(
                "create_todo",
                {"title": "准备面试", "due_date": TOMORROW},
                confirmed=True,
            )

        self.assertEqual(result.error.type, ErrorType.MISSING_IDEMPOTENCY_KEY)

    def test_confirmed_create_with_key_succeeds(self) -> None:
        result = self.create_via_dispatch(
            user_a(), "准备面试", TOMORROW, request_id="req-1"
        )

        self.assertEqual(result.status, "success")

    def test_replay_with_same_key_creates_one_todo(self) -> None:
        first = self.create_via_dispatch(
            user_a(), "准备面试", TOMORROW, request_id="req-1"
        )
        second = self.create_via_dispatch(
            user_a(), "准备面试", TOMORROW, request_id="req-1"
        )

        self.assertEqual(first.data, second.data)

        with use_context(user_a()):
            listing = dispatch_tool("list_todos", {})

        self.assertEqual(listing.data["total_matched"], 1)

    def test_same_content_with_new_key_is_rejected_by_business_rule(self) -> None:
        first = self.create_via_dispatch(
            user_a(), "准备面试", TOMORROW, request_id="req-1"
        )
        second = self.create_via_dispatch(
            user_a(), "准备面试", TOMORROW, request_id="req-2"
        )

        self.assertEqual(first.status, "success")
        self.assertEqual(second.error.type, ErrorType.TODO_ALREADY_EXISTS)

    def test_past_due_date_rejected_through_dispatch(self) -> None:
        result = self.create_via_dispatch(
            user_a(), "准备面试", YESTERDAY, request_id="req-1"
        )

        self.assertEqual(result.error.type, ErrorType.INVALID_TIME_RANGE)

    def test_blank_title_is_rejected_before_handler(self) -> None:
        result = self.create_via_dispatch(
            user_a(), "   ", TOMORROW, request_id="req-1"
        )

        self.assertEqual(result.error.type, ErrorType.INVALID_ARGUMENTS)

    def test_bad_date_format_is_rejected_before_handler(self) -> None:
        result = self.create_via_dispatch(
            user_a(), "准备面试", "明天", request_id="req-1"
        )

        self.assertEqual(result.error.type, ErrorType.INVALID_ARGUMENTS)

    def test_list_todos_is_read_only_and_needs_no_key(self) -> None:
        with use_context(user_a()):
            result = dispatch_tool("list_todos", {})

        self.assertEqual(result.status, "success")

    def test_tool_configuration_locks_governance_rules(self) -> None:
        self.assertEqual(CREATE_TODO_TOOL.risk_level, "write")
        self.assertTrue(CREATE_TODO_TOOL.requires_confirmation)
        # 写入工具不得开启超时重试。
        self.assertFalse(CREATE_TODO_TOOL.retryable_on_timeout)


if __name__ == "__main__":
    unittest.main()
