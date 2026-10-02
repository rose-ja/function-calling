import unittest

from main import dispatch_tool
from tool_core import ToolResult
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


class DispatcherTests(unittest.TestCase):
    def test_registered_tool_uses_weather_implementation(self) -> None:
        result = dispatch_tool("get_weather", {"city": "上海"})

        self.assertIsInstance(result, ToolResult)
        self.assertEqual(result.status, "success")
        self.assertEqual(result.data["condition"], "cloudy")

    def test_unknown_tool_is_not_executed(self) -> None:
        result = dispatch_tool("search_weather", {"city": "北京"})

        self.assertEqual(result.status, "error")
        self.assertEqual(result.error.type, "UNKNOWN_TOOL")
        self.assertFalse(result.error.retryable)

    def test_invalid_tool_name_is_rejected(self) -> None:
        result = dispatch_tool(None, {"city": "北京"})

        self.assertEqual(result.error.type, "INVALID_TOOL_NAME")

    def test_arguments_must_be_an_object(self) -> None:
        result = dispatch_tool("get_weather", ["北京"])

        self.assertEqual(result.error.type, "INVALID_ARGUMENTS")

    def test_extra_field_is_rejected_before_handler_runs(self) -> None:
        result = dispatch_tool("get_weather", {"city": "北京", "force": True})

        self.assertEqual(result.error.type, "INVALID_ARGUMENTS")

    def test_unsupported_city_is_preserved(self) -> None:
        result = dispatch_tool("get_weather", {"city": "广州"})

        self.assertEqual(result.error.type, "CITY_NOT_SUPPORTED")

    def test_write_tool_requires_confirmation(self) -> None:
        registry = {"assign_order": build_fake_write_tool()}

        blocked = dispatch_tool("assign_order", {}, registry=registry)
        self.assertEqual(blocked.status, "error")
        self.assertEqual(blocked.error.type, "CONFIRMATION_REQUIRED")

        allowed = dispatch_tool("assign_order", {}, confirmed=True, registry=registry)
        self.assertEqual(allowed.status, "success")
        self.assertTrue(allowed.data["assigned"])


if __name__ == "__main__":
    unittest.main()