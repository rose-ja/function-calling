import unittest

from dispatcher import dispatch_tool
from exchange_rate_tool import execute_exchange_rate
from tool_core import ErrorType, ExecutionState


class ExchangeRateToolTests(unittest.TestCase):
    """业务层：直接调用 handler，只验证业务规则。"""

    def test_supported_pair_returns_rate(self) -> None:
        result = execute_exchange_rate(
            {"base_currency": "CNY", "quote_currency": "USD"}
        )

        self.assertEqual(result.status, "success")
        self.assertEqual(result.data["rate"], "0.14")

    def test_amount_is_converted_with_two_decimals(self) -> None:
        result = execute_exchange_rate(
            {"base_currency": "CNY", "quote_currency": "USD", "amount": 1000}
        )

        self.assertEqual(result.data["converted_amount"], "140.00")

    def test_missing_amount_omits_conversion_fields(self) -> None:
        result = execute_exchange_rate(
            {"base_currency": "CNY", "quote_currency": "USD"}
        )

        self.assertNotIn("amount", result.data)
        self.assertNotIn("converted_amount", result.data)

    def test_same_currency_needs_no_rate_lookup(self) -> None:
        result = execute_exchange_rate(
            {"base_currency": "CNY", "quote_currency": "CNY"}
        )

        self.assertEqual(result.status, "success")
        self.assertEqual(result.data["rate"], "1")

    def test_half_up_rounding_is_used_for_money(self) -> None:
        # Python 的 round(2.675, 2) 会得到 2.67（银行家舍入），金额不能这样处理。
        result = execute_exchange_rate(
            {"base_currency": "CNY", "quote_currency": "CNY", "amount": 2.675}
        )

        self.assertEqual(result.data["converted_amount"], "2.68")

    def test_direction_matters(self) -> None:
        forward = execute_exchange_rate(
            {"base_currency": "CNY", "quote_currency": "USD"}
        )
        backward = execute_exchange_rate(
            {"base_currency": "USD", "quote_currency": "CNY"}
        )

        self.assertEqual(forward.data["rate"], "0.14")
        self.assertEqual(backward.data["rate"], "7.12")

    def test_unsupported_pair_is_business_error(self) -> None:
        result = execute_exchange_rate(
            {"base_currency": "CNY", "quote_currency": "EUR"}
        )

        self.assertEqual(result.status, "error")
        self.assertEqual(result.error.type, ErrorType.RATE_NOT_SUPPORTED)
        self.assertFalse(result.error.retryable)
        self.assertEqual(result.error.execution_state, ExecutionState.NOT_EXECUTED)


class ExchangeRateContractTests(unittest.TestCase):
    """契约层：必须走 dispatch_tool，Schema 校验才会参与。"""

    def test_lowercase_currency_code_is_rejected(self) -> None:
        result = dispatch_tool(
            "get_exchange_rate",
            {"base_currency": "cny", "quote_currency": "USD"},
        )

        self.assertEqual(result.error.type, ErrorType.INVALID_ARGUMENTS)

    def test_currency_code_with_wrong_length_is_rejected(self) -> None:
        result = dispatch_tool(
            "get_exchange_rate",
            {"base_currency": "CN", "quote_currency": "USD"},
        )

        self.assertEqual(result.error.type, ErrorType.INVALID_ARGUMENTS)

    def test_non_positive_amount_is_rejected(self) -> None:
        for amount in (0, -5):
            with self.subTest(amount=amount):
                result = dispatch_tool(
                    "get_exchange_rate",
                    {
                        "base_currency": "CNY",
                        "quote_currency": "USD",
                        "amount": amount,
                    },
                )
                self.assertEqual(result.error.type, ErrorType.INVALID_ARGUMENTS)

    def test_unknown_field_is_rejected(self) -> None:
        result = dispatch_tool(
            "get_exchange_rate",
            {
                "base_currency": "CNY",
                "quote_currency": "USD",
                "rate": 99,
            },
        )

        self.assertEqual(result.error.type, ErrorType.INVALID_ARGUMENTS)
        self.assertIn("$.rate", result.error.message)

    def test_unsupported_pair_reaches_business_layer(self) -> None:
        # 格式合法但业务不支持，应当走到业务层并返回业务错误码。
        result = dispatch_tool(
            "get_exchange_rate",
            {"base_currency": "CNY", "quote_currency": "EUR"},
        )

        self.assertEqual(result.error.type, ErrorType.RATE_NOT_SUPPORTED)


if __name__ == "__main__":
    unittest.main()