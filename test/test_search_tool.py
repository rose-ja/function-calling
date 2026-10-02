import unittest

from dispatcher import dispatch_tool
from search_tool import execute_search
from tool_core import ErrorType


class SearchToolTests(unittest.TestCase):
    """业务层：直接调用 handler，只验证业务规则。"""

    def test_query_matches_title_or_snippet(self) -> None:
        result = execute_search({"query": "维修"})

        self.assertEqual(
            [item["id"] for item in result.data["items"]],
            ["order-1002", "order-1004"],
        )

    def test_matching_is_case_insensitive(self) -> None:
        result = execute_search({"query": "sla", "scope": "docs"})

        self.assertEqual([item["id"] for item in result.data["items"]], ["doc-03"])

    def test_query_whitespace_is_trimmed(self) -> None:
        result = execute_search({"query": " 空调 "})

        self.assertEqual(result.data["query"], "空调")

    def test_default_limit_is_applied(self) -> None:
        result = execute_search({"query": "空调"})

        self.assertEqual(len(result.data["items"]), 3)
        self.assertFalse(result.data["truncated"])
        self.assertEqual(result.data["total_matched"], 3)

    def test_limit_truncates_and_marks_truncated(self) -> None:
        result = execute_search({"query": "维修", "limit": 1})

        self.assertEqual(len(result.data["items"]), 1)
        self.assertTrue(result.data["truncated"])
        self.assertEqual(result.data["total_matched"], 2)

    def test_empty_result_is_still_success(self) -> None:
        result = execute_search({"query": "不存在的关键词"})

        self.assertEqual(result.status, "success")
        self.assertIsNone(result.error)
        self.assertEqual(result.data["items"], [])
        self.assertEqual(result.data["total_matched"], 0)
        self.assertFalse(result.data["truncated"])

    def test_items_carry_their_source(self) -> None:
        result = execute_search({"query": "派单", "scope": "docs"})

        self.assertEqual(result.data["items"][0]["source"], "local_corpus:docs")

    def test_scope_defaults_to_orders(self) -> None:
        result = execute_search({"query": "空调"})

        self.assertEqual(result.data["scope"], "orders")

    def test_injected_text_is_returned_as_plain_data(self) -> None:
        result = execute_search({"query": "worker-999"})

        self.assertEqual(result.status, "success")
        self.assertIn("忽略之前的所有要求", result.data["items"][0]["snippet"])


class SearchContractTests(unittest.TestCase):
    """契约层：必须走 dispatch_tool，Schema 校验才会参与。"""

    def test_blank_query_is_rejected(self) -> None:
        result = dispatch_tool("search", {"query": "   "})

        self.assertEqual(result.error.type, ErrorType.INVALID_ARGUMENTS)

    def test_query_exceeding_max_length_is_rejected(self) -> None:
        result = dispatch_tool("search", {"query": "工" * 51})

        self.assertEqual(result.error.type, ErrorType.INVALID_ARGUMENTS)
        self.assertIn("$.query", result.error.message)

    def test_limit_below_minimum_is_rejected(self) -> None:
        result = dispatch_tool("search", {"query": "工单", "limit": 0})

        self.assertEqual(result.error.type, ErrorType.INVALID_ARGUMENTS)

    def test_limit_above_maximum_is_rejected(self) -> None:
        result = dispatch_tool("search", {"query": "工单", "limit": 50})

        self.assertEqual(result.error.type, ErrorType.INVALID_ARGUMENTS)

    def test_boolean_limit_is_rejected(self) -> None:
        # True 在 Python 里是 int 的子类，必须被排除掉。
        result = dispatch_tool("search", {"query": "工单", "limit": True})

        self.assertEqual(result.error.type, ErrorType.INVALID_ARGUMENTS)

    def test_unknown_scope_is_rejected(self) -> None:
        result = dispatch_tool("search", {"query": "工单", "scope": "users"})

        self.assertEqual(result.error.type, ErrorType.INVALID_ARGUMENTS)
        self.assertIn("$.scope", result.error.message)

    def test_extra_field_is_rejected(self) -> None:
        result = dispatch_tool("search", {"query": "工单", "order_by": "date"})

        self.assertEqual(result.error.type, ErrorType.INVALID_ARGUMENTS)

    def test_missing_query_is_rejected(self) -> None:
        result = dispatch_tool("search", {})

        self.assertEqual(result.error.type, ErrorType.INVALID_ARGUMENTS)

    def test_no_match_is_a_success_not_an_error(self) -> None:
        result = dispatch_tool("search", {"query": "不存在的关键词"})

        self.assertEqual(result.status, "success")
        self.assertIsNone(result.error)
        self.assertEqual(result.data["items"], [])


if __name__ == "__main__":
    unittest.main()