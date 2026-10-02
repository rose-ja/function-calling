import unittest

from tool_core import ToolError, ToolResult
from weather_tool import execute_weather


class WeatherToolTests(unittest.TestCase):
    def test_beijing_query_succeeds(self) -> None:
        result = execute_weather({"city": "北京"})

        self.assertEqual(result.status, "success")
        self.assertEqual(
            result.data,
            {
                "city": "北京",
                "condition": "rain",
                "temperature_celsius": 22,
            },
        )
        self.assertIsNone(result.error)

    def test_unsupported_city_is_business_error(self) -> None:
        result = execute_weather({"city": "广州"})

        self.assertEqual(result.status, "error")
        self.assertIsNone(result.data)
        self.assertEqual(result.error.type, "CITY_NOT_SUPPORTED")
        self.assertFalse(result.error.retryable)

    def test_city_whitespace_is_trimmed(self) -> None:
        result = execute_weather({"city": " 北京 "})

        self.assertEqual(result.status, "success")
        self.assertEqual(result.data["city"], "北京")

    def test_result_rejects_conflicting_success_and_error(self) -> None:
        with self.assertRaises(ValueError):
            ToolResult(
                status="success",
                data={"city": "北京"},
                error=ToolError(
                    type="INTERNAL_ERROR",
                    message="不应同时存在",
                    retryable=False,
                ),
            )


if __name__ == "__main__":
    unittest.main()