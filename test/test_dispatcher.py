import unittest

from dispatcher import TOOL_REGISTRY, dispatch_tool
from tool_core import ErrorType, ToolResult
from tool_spec import ToolSpec


def build_fake_write_tool() -> ToolSpec:
    return ToolSpec(
        name="assign_order",
        description="修改工单负责人；会写入业务数据",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        handler=lambda arguments: ToolResult.success({"assigned": True}),
        risk_level="write",
        requires_confirmation=True,
    )


def build_exploding_tool() -> ToolSpec:
    def handler(arguments: dict[str, object]) -> ToolResult:
        raise RuntimeError("数据库连接串：postgres://internal-host/app")

    return ToolSpec(
        name="boom",
        description="故意抛异常的工具，用于验证兜底行为",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        handler=handler,
    )


class DispatcherPolicyTests(unittest.TestCase):
    def test_registry_exposes_weather_tool(self) -> None:
        self.assertEqual(sorted(TOOL_REGISTRY), ["get_exchange_rate", "get_weather"])

    def test_registered_tool_runs_through_registry(self) -> None:
        result = dispatch_tool("get_weather", {"city": "上海"})

        self.assertIsInstance(result, ToolResult)
        self.assertEqual(result.status, "success")
        self.assertEqual(result.data["condition"], "cloudy")

    def test_unknown_tool_is_not_executed(self) -> None:
        result = dispatch_tool("search_weather", {"city": "北京"})

        self.assertEqual(result.status, "error")
        self.assertEqual(result.error.type, ErrorType.UNKNOWN_TOOL)
        self.assertFalse(result.error.retryable)

    def test_blank_or_non_string_tool_name_is_rejected(self) -> None:
        for tool_name in (None, "", "   ", 123):
            with self.subTest(tool_name=tool_name):
                result = dispatch_tool(tool_name, {"city": "北京"})
                self.assertEqual(result.error.type, ErrorType.INVALID_TOOL_NAME)

    def test_non_object_arguments_are_rejected(self) -> None:
        result = dispatch_tool("get_weather", ["北京"])

        self.assertEqual(result.error.type, ErrorType.INVALID_ARGUMENTS)

    def test_extra_field_is_rejected_before_handler_runs(self) -> None:
        result = dispatch_tool("get_weather", {"city": "北京", "force": True})

        self.assertEqual(result.error.type, ErrorType.INVALID_ARGUMENTS)

    def test_business_error_is_passed_through_unchanged(self) -> None:
        result = dispatch_tool("get_weather", {"city": "广州"})

        self.assertEqual(result.error.type, ErrorType.CITY_NOT_SUPPORTED)

    def test_write_tool_requires_confirmation(self) -> None:
        registry = {"assign_order": build_fake_write_tool()}

        blocked = dispatch_tool("assign_order", {}, registry=registry)
        self.assertEqual(blocked.status, "error")
        self.assertEqual(blocked.error.type, ErrorType.CONFIRMATION_REQUIRED)

        allowed = dispatch_tool("assign_order", {}, confirmed=True, registry=registry)
        self.assertEqual(allowed.status, "success")
        self.assertTrue(allowed.data["assigned"])

    def test_unexpected_exception_becomes_internal_error(self) -> None:
        registry = {"boom": build_exploding_tool()}

        result = dispatch_tool("boom", {}, registry=registry)

        self.assertEqual(result.error.type, ErrorType.INTERNAL_ERROR)
        self.assertEqual(result.error.message, "工具执行时发生内部错误")

    def test_internal_error_does_not_leak_exception_details(self) -> None:
        registry = {"boom": build_exploding_tool()}

        result = dispatch_tool("boom", {}, registry=registry)

        self.assertNotIn("postgres", result.error.message)
        self.assertNotIn("Traceback", result.error.message)


if __name__ == "__main__":
    unittest.main()