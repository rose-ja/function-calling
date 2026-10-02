import unittest

from tool_core import ErrorType, ExecutionState
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

    def test_shanghai_query_succeeds(self) -> None:
        result = execute_weather({"city": "上海"})

        self.assertEqual(result.data["condition"], "cloudy")

    def test_city_whitespace_is_trimmed(self) -> None:
        result = execute_weather({"city": " 北京 "})

        self.assertEqual(result.status, "success")
        self.assertEqual(result.data["city"], "北京")

    def test_unsupported_city_is_business_error(self) -> None:
        result = execute_weather({"city": "广州"})

        self.assertEqual(result.status, "error")
        self.assertIsNone(result.data)
        self.assertEqual(result.error.type, ErrorType.CITY_NOT_SUPPORTED)
        self.assertFalse(result.error.retryable)

    def test_business_error_means_nothing_was_executed(self) -> None:
        result = execute_weather({"city": "广州"})

        self.assertEqual(result.error.execution_state, ExecutionState.NOT_EXECUTED)


if __name__ == "__main__":
    unittest.main()