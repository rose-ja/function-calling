import unittest

from app.tool_core import ErrorType, ExecutionState, ToolResult
from app.tool_spec import ToolSpec, run_tool
from app.weather_tool import WEATHER_PARAMETERS, WEATHER_TOOL


def build_spec(**overrides: object) -> ToolSpec:
    base: dict[str, object] = {
        "name": "noop",
        "description": "测试用工具",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        "handler": lambda arguments: ToolResult.success({}),
    }
    base.update(overrides)
    return ToolSpec(**base)  # type: ignore[arg-type]


class ToolSpecConstructionTests(unittest.TestCase):
    def test_blank_name_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            build_spec(name="   ")

    def test_parameters_must_be_an_object_schema(self) -> None:
        with self.assertRaises(ValueError):
            build_spec(parameters={"type": "array"})

    def test_read_tool_may_retry_on_timeout(self) -> None:
        spec = build_spec(risk_level="read", retryable_on_timeout=True)

        self.assertTrue(spec.retryable_on_timeout)

    def test_write_tool_cannot_retry_on_timeout(self) -> None:
        # 写入超时可能已经生效，直接重试会制造重复数据。
        with self.assertRaises(ValueError):
            build_spec(risk_level="write", retryable_on_timeout=True)

    def test_confirmation_requires_write_risk(self) -> None:
        with self.assertRaises(ValueError):
            build_spec(risk_level="read", requires_confirmation=True)

    def test_non_positive_timeout_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            build_spec(timeout_seconds=0)

    def test_unknown_risk_level_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            build_spec(risk_level="dangerous")


class WeatherToolContractTests(unittest.TestCase):
    def test_model_schema_matches_registered_parameters(self) -> None:
        schema = WEATHER_TOOL.to_model_schema()

        self.assertEqual(schema["type"], "function")
        self.assertEqual(schema["function"]["name"], "get_weather")
        self.assertEqual(schema["function"]["parameters"], WEATHER_PARAMETERS)

    def test_description_states_the_tool_is_read_only(self) -> None:
        self.assertIn("不修改任何业务信息", WEATHER_TOOL.description)

    def test_extra_fields_are_forbidden(self) -> None:
        self.assertIs(WEATHER_PARAMETERS["additionalProperties"], False)


class RunToolTests(unittest.TestCase):
    def test_invalid_arguments_never_reach_handler(self) -> None:
        received: list[object] = []

        def handler(arguments: dict[str, object]) -> ToolResult:
            received.append(arguments)
            return ToolResult.success({"called": True})

        spec = build_spec(handler=handler)

        result = run_tool(spec, {"unexpected": 1})

        self.assertEqual(result.error.type, ErrorType.INVALID_ARGUMENTS)
        self.assertEqual(received, [])
        self.assertEqual(result.error.execution_state, ExecutionState.NOT_EXECUTED)


if __name__ == "__main__":
    unittest.main()