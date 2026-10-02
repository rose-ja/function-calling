from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, Sequence

from dispatcher import TOOL_REGISTRY, dispatch_tool
from request_context import RequestContext, use_context
from tool_core import ErrorType, ToolResult
from tool_spec import ToolSpec


StopReason = Literal[
    "ROUND_LIMIT",
    "CALL_LIMIT",
    "CORRECTION_LIMIT",
    "CONFIRMATION_REQUIRED",
    "MODEL_OUTPUT_EXHAUSTED",
]

# 只有“请求本身写错了”这一类错误，模型重新提一次才有意义。
# 权限、身份、业务规则、超时、内部错误都不属于可纠正范围。
CORRECTABLE_ERRORS = frozenset(
    {
        ErrorType.UNKNOWN_TOOL,
        ErrorType.INVALID_TOOL_NAME,
        ErrorType.INVALID_ARGUMENTS,
    }
)


class ModelOutputExhausted(RuntimeError):
    """模型没有产生新的输出（脚本用尽或模型服务不可用）。"""


@dataclass(frozen=True)
class ToolCall:
    """模型提出的一次工具调用。这两个字段都是不可信输入。"""

    tool_name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ModelTurn:
    """模型的一轮输出：要么提出一次工具调用，要么给出最终答复。"""

    tool_call: ToolCall | None = None
    final_answer: str | None = None

    def __post_init__(self) -> None:
        if (self.tool_call is None) == (self.final_answer is None):
            raise ValueError("一轮输出必须且只能包含工具调用或最终答复之一")


class ModelClient(Protocol):
    """模型接口。

    真实项目里这里是 LLM 客户端。把模型抽象成接口之后，
    Agent 循环的控制逻辑就能脱离网络和密钥被单独测试。
    """

    def next_turn(self, history: Sequence[dict[str, Any]]) -> ModelTurn: ...


class ScriptedModel:
    """按脚本返回轮次的假模型，用于测试和演示。"""

    def __init__(self, turns: Sequence[ModelTurn]) -> None:
        if not turns:
            raise ValueError("脚本至少要有一轮输出")
        self._turns = list(turns)
        self._index = 0
        self.seen_histories: list[list[dict[str, Any]]] = []

    def next_turn(self, history: Sequence[dict[str, Any]]) -> ModelTurn:
        self.seen_histories.append([dict(entry) for entry in history])

        if self._index >= len(self._turns):
            raise ModelOutputExhausted("脚本已用尽")

        turn = self._turns[self._index]
        self._index += 1
        return turn


@dataclass(frozen=True)
class AgentBudget:
    """循环的硬边界。这些值由应用决定，模型无权修改。"""

    max_rounds: int = 6
    max_tool_calls: int = 8
    max_corrections: int = 2

    def __post_init__(self) -> None:
        for field_name, value in (
            ("max_rounds", self.max_rounds),
            ("max_tool_calls", self.max_tool_calls),
            ("max_corrections", self.max_corrections),
        ):
            if not isinstance(value, int) or isinstance(value, bool):
                raise TypeError(f"{field_name} 必须是整数")
            if value < 1:
                raise ValueError(f"{field_name} 至少为 1")


@dataclass(frozen=True)
class AgentStep:
    """一步的审计记录：模型提了什么、系统回了什么。"""

    round_index: int
    call: ToolCall
    result: ToolResult


@dataclass(frozen=True)
class AgentRun:
    status: Literal["completed", "stopped"]
    answer: str | None
    stop_reason: StopReason | None
    steps: tuple[AgentStep, ...] = field(default_factory=tuple)

    @property
    def tool_calls(self) -> int:
        return len(self.steps)


def serialize_result(result: ToolResult) -> dict[str, Any]:
    """把 ToolResult 转成回传给模型的结构。

    只包含模型能用来决定下一步的信息：错误码、可读说明、是否可重试、执行状态。
    内部堆栈和内部标识永远不出现在这里。
    """
    if result.status == "success":
        return {"status": "success", "data": result.data}

    error = result.error
    return {
        "status": "error",
        "error_type": error.type.value,
        "message": error.message,
        "retryable": error.retryable,
        "execution_state": error.execution_state.value,
    }


def derive_idempotency_key(
    context: RequestContext,
    tool_name: str,
    arguments: dict[str, Any],
) -> str:
    """按“工具 + 规范化参数”生成请求指纹。

    这样模型重复提出完全相同的调用会被幂等层去重；参数不同则视为不同的业务请求。

    取舍：这只是可行方案之一。如果业务允许“同样内容创建两次”，
    就不能用参数指纹，必须让调用方显式提供业务请求标识。
    """
    canonical = json.dumps(arguments, ensure_ascii=False, sort_keys=True)
    fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]
    return context.idempotency_key(tool_name, fingerprint)


def run_agent(
    user_request: str,
    model: ModelClient,
    *,
    context: RequestContext,
    budget: AgentBudget | None = None,
    confirmed: bool = False,
    registry: dict[str, ToolSpec] | None = None,
) -> AgentRun:
    """在应用控制的边界内运行一次 Agent 循环。"""
    if not isinstance(user_request, str) or not user_request.strip():
        raise ValueError("user_request 必须是非空字符串")
    if not isinstance(context, RequestContext):
        raise TypeError("context 必须是 RequestContext")

    active_budget = budget or AgentBudget()
    specs = TOOL_REGISTRY if registry is None else registry

    steps: list[AgentStep] = []
    corrections = 0
    tool_call_count = 0

    with use_context(context):
        history: list[dict[str, Any]] = [
            {"role": "user", "content": user_request}
        ]

        for round_index in range(1, active_budget.max_rounds + 1):
            try:
                turn = model.next_turn(history)
            except ModelOutputExhausted:
                # 模型没有新输出：立刻停下，不要空转。
                return _stopped("MODEL_OUTPUT_EXHAUSTED", steps)

            if turn.final_answer is not None:
                return AgentRun(
                    status="completed",
                    answer=turn.final_answer,
                    stop_reason=None,
                    steps=tuple(steps),
                )

            call = turn.tool_call
            if call is None:  # ModelTurn 已经保证二选一，这里只是让类型更明确
                return _stopped("MODEL_OUTPUT_EXHAUSTED", steps)

            if tool_call_count >= active_budget.max_tool_calls:
                return _stopped("CALL_LIMIT", steps)

            tool_call_count += 1
            result = dispatch_tool(
                call.tool_name,
                call.arguments,
                confirmed=confirmed,
                idempotency_key=derive_idempotency_key(
                    context, call.tool_name, call.arguments
                ),
                registry=specs,
            )
            steps.append(AgentStep(round_index, call, result))

            if result.status == "error" and result.error is not None:
                error_type = result.error.type

                if error_type is ErrorType.CONFIRMATION_REQUIRED:
                    # 写操作必须由用户表态，循环不能自行往下走。
                    return _stopped("CONFIRMATION_REQUIRED", steps)

                if error_type in CORRECTABLE_ERRORS:
                    corrections += 1
                    if corrections > active_budget.max_corrections:
                        return _stopped("CORRECTION_LIMIT", steps)

            history.append(_feedback_entry(call, result, specs))

        return _stopped("ROUND_LIMIT", steps)


def _feedback_entry(
    call: ToolCall,
    result: ToolResult,
    specs: dict[str, ToolSpec],
) -> dict[str, Any]:
    payload = serialize_result(result)

    if result.status == "error" and result.error is not None:
        if result.error.type is ErrorType.UNKNOWN_TOOL:
            # 只在工具名出错时提示可用工具，而且只提示注册表里的名字。
            payload = {**payload, "available_tools": sorted(specs)}

    return {"role": "tool", "tool_name": call.tool_name, "result": payload}


def _stopped(reason: StopReason, steps: list[AgentStep]) -> AgentRun:
    return AgentRun(
        status="stopped",
        answer=None,
        stop_reason=reason,
        steps=tuple(steps),
    )
