import unittest

from main import dispatch_tool
from tool_core import ToolResult


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

    def test_weather_parameter_error_is_preserved(self) -> None:
        result = dispatch_tool("get_weather", {"city": ""})

        self.assertEqual(result.error.type, "INVALID_ARGUMENTS")

    def test_unsupported_city_is_preserved(self) -> None:
        result = dispatch_tool("get_weather", {"city": "广州"})

        self.assertEqual(result.error.type, "CITY_NOT_SUPPORTED")


if __name__ == "__main__":
    unittest.main()