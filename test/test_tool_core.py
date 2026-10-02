import unittest

from tool_core import ErrorType, ExecutionState, ToolError, ToolResult


class ToolResultTests(unittest.TestCase):
    def test_success_builds_expected_result(self) -> None:
        result = ToolResult.success({"city": "北京"})

        self.assertEqual(result.status, "success")
        self.assertEqual(result.data, {"city": "北京"})
        self.assertIsNone(result.error)

    def test_success_requires_data(self) -> None:
        with self.assertRaises(ValueError):
            ToolResult(status="success")

    def test_success_cannot_carry_error(self) -> None:
        with self.assertRaises(ValueError):
            ToolResult(
                status="success",
                data={"city": "北京"},
                error=ToolError(
                    type=ErrorType.INTERNAL_ERROR,
                    message="不应同时存在",
                ),
            )

    def test_failure_requires_error(self) -> None:
        with self.assertRaises(ValueError):
            ToolResult(status="error")

    def test_failure_cannot_carry_data(self) -> None:
        with self.assertRaises(ValueError):
            ToolResult(
                status="error",
                data={"city": "北京"},
                error=ToolError(
                    type=ErrorType.INTERNAL_ERROR,
                    message="不应同时存在",
                ),
            )

    def test_unknown_status_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ToolResult(status="partial")  # type: ignore[arg-type]

    def test_failure_defaults_to_not_executed(self) -> None:
        result = ToolResult.failure(ErrorType.UNKNOWN_TOOL, "未注册的工具")

        self.assertEqual(result.error.type, ErrorType.UNKNOWN_TOOL)
        self.assertEqual(result.error.execution_state, ExecutionState.NOT_EXECUTED)
        self.assertFalse(result.error.retryable)

    def test_error_message_must_not_be_blank(self) -> None:
        with self.assertRaises(ValueError):
            ToolError(type=ErrorType.INTERNAL_ERROR, message="   ")

    def test_error_type_must_be_declared(self) -> None:
        with self.assertRaises(TypeError):
            ToolError(type="UNKNOWN_TOOL", message="用了裸字符串")  # type: ignore[arg-type]

    def test_error_type_compares_as_plain_string(self) -> None:
        # str 枚举可以直接和字符串比较，便于序列化后回读。
        self.assertEqual(ErrorType.UNKNOWN_TOOL, "UNKNOWN_TOOL")


if __name__ == "__main__":
    unittest.main()