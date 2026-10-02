from __future__ import annotations

import threading
from datetime import date
from itertools import count
from typing import Any

from request_context import MissingIdentityError, current_context
from tool_core import ErrorType, ToolResult
from tool_spec import ToolSpec


DEFAULT_LIST_LIMIT = 10

LIST_TODOS_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "limit": {
            "type": "integer",
            "description": "最多返回条数，可选，默认 10，取值范围 1 到 20",
            "minimum": 1,
            "maximum": 20,
        },
    },
    "required": [],
    "additionalProperties": False,
}

# 这份 Schema 里没有 owner_id，这是刻意的：
# 待办归属只能来自请求身份，否则模型可以传别人的 id 去读写别人的数据。
CREATE_TODO_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {
            "type": "string",
            "description": "待办标题，1 到 50 个字符",
            "minLength": 1,
            "maxLength": 50,
            "pattern": r"\S",
        },
        "due_date": {
            "type": "string",
            "description": "截止日期，格式 YYYY-MM-DD，不能早于今天",
            "pattern": r"^\d{4}-\d{2}-\d{2}$",
        },
    },
    "required": ["title", "due_date"],
    "additionalProperties": False,
}


_LOCK = threading.Lock()
_TODOS: dict[str, dict[str, Any]] = {}
_SEQUENCE = count(1)


def reset_todos() -> None:
    """清空待办数据。只给测试和演示使用。"""
    global _SEQUENCE
    with _LOCK:
        _TODOS.clear()
        _SEQUENCE = count(1)


def _public_view(todo: dict[str, Any]) -> dict[str, Any]:
    """返回副本：外部拿到结果之后不应该能改到内部数据。"""
    return dict(todo)


def _todos_of(owner_id: str) -> list[dict[str, Any]]:
    return [todo for todo in _TODOS.values() if todo["owner_id"] == owner_id]


def _find_same_todo(
    owner_id: str,
    title: str,
    due_date: str,
) -> dict[str, Any] | None:
    for todo in _TODOS.values():
        if (
            todo["owner_id"] == owner_id
            and todo["title"] == title
            and todo["due_date"] == due_date
        ):
            return todo
    return None


def execute_list_todos(arguments: dict[str, Any]) -> ToolResult:
    try:
        context = current_context()
    except MissingIdentityError:
        return ToolResult.failure(
            ErrorType.IDENTITY_REQUIRED,
            "缺少请求身份，无法查询个人待办",
        )

    limit = arguments.get("limit", DEFAULT_LIST_LIMIT)

    with _LOCK:
        owned = _todos_of(context.actor_id)

    items = [_public_view(todo) for todo in owned[:limit]]

    # 没有待办是正常结果，不是系统故障。
    return ToolResult.success(
        {
            "owner_id": context.actor_id,
            "items": items,
            "total_matched": len(owned),
            "truncated": len(owned) > len(items),
        }
    )


def execute_create_todo(arguments: dict[str, Any]) -> ToolResult:
    try:
        context = current_context()
    except MissingIdentityError:
        return ToolResult.failure(
            ErrorType.IDENTITY_REQUIRED,
            "缺少请求身份，无法创建个人待办",
        )

    title = arguments["title"].strip()
    due_date = arguments["due_date"]

    if date.fromisoformat(due_date) < date.today():
        return ToolResult.failure(
            ErrorType.INVALID_TIME_RANGE,
            f"截止日期不能早于今天：{due_date}",
        )

    with _LOCK:
        existing = _find_same_todo(context.actor_id, title, due_date)
        if existing is not None:
            # 业务去重：用户确实试图创建一条已存在的待办。
            # 这和“同一个请求被提交两次”不是一回事，那是幂等键管的。
            return ToolResult.failure(
                ErrorType.TODO_ALREADY_EXISTS,
                f"同一天已存在同名待办：{title}（{due_date}）",
            )

        todo_id = f"todo-{next(_SEQUENCE):03d}"
        todo: dict[str, Any] = {
            "todo_id": todo_id,
            "title": title,
            "due_date": due_date,
            "owner_id": context.actor_id,
        }
        _TODOS[todo_id] = todo

    return ToolResult.success({"created": True, **_public_view(todo)})


LIST_TODOS_TOOL = ToolSpec(
    name="list_todos",
    description="查询当前用户的待办列表；只读取数据",
    parameters=LIST_TODOS_PARAMETERS,
    handler=execute_list_todos,
    risk_level="read",
    timeout_seconds=3.0,
    retryable_on_timeout=True,
)

CREATE_TODO_TOOL = ToolSpec(
    name="create_todo",
    description="为当前用户创建一条待办；会写入业务数据，需要用户确认与幂等键",
    parameters=CREATE_TODO_PARAMETERS,
    handler=execute_create_todo,
    risk_level="write",
    requires_confirmation=True,
    # 写入工具故意不开超时重试：超时后是否已创建无法确认。
    timeout_seconds=5.0,
)
