import unittest

from app.tool_schema import validate_arguments


SCHEMA = {
    "type": "object",
    "properties": {
        "city": {"type": "string", "minLength": 1, "pattern": r"\S"},
        "days": {"type": "integer", "minimum": 1, "maximum": 7},
        "amount": {"type": "number", "exclusiveMinimum": 0},
        "tags": {"type": "array", "maxItems": 2, "items": {"type": "string"}},
    },
    "required": ["city"],
    "additionalProperties": False,
}


def issue_paths(arguments: object) -> list[str]:
    return [issue.path for issue in validate_arguments(SCHEMA, arguments)]


class SchemaValidationTests(unittest.TestCase):
    def test_valid_arguments_pass(self) -> None:
        self.assertEqual(
            validate_arguments(SCHEMA, {"city": "北京", "days": 3, "amount": 1.5}),
            [],
        )

    def test_arguments_must_be_object(self) -> None:
        self.assertEqual(issue_paths(["北京"]), ["$"])

    def test_missing_required_field(self) -> None:
        self.assertEqual(issue_paths({}), ["$.city"])

    def test_blank_string_is_rejected(self) -> None:
        self.assertEqual(issue_paths({"city": "   "}), ["$.city"])

    def test_extra_field_is_rejected(self) -> None:
        self.assertEqual(issue_paths({"city": "北京", "force": True}), ["$.force"])

    def test_wrong_type_is_rejected(self) -> None:
        self.assertEqual(issue_paths({"city": 123}), ["$.city"])

    def test_boolean_is_not_an_integer(self) -> None:
        self.assertEqual(issue_paths({"city": "北京", "days": True}), ["$.days"])

    def test_out_of_range_integer_is_rejected(self) -> None:
        self.assertEqual(issue_paths({"city": "北京", "days": 30}), ["$.days"])

    def test_zero_violates_exclusive_minimum(self) -> None:
        self.assertEqual(issue_paths({"city": "北京", "amount": 0}), ["$.amount"])

    def test_array_items_are_validated(self) -> None:
        self.assertEqual(issue_paths({"city": "北京", "tags": ["a", 1]}), ["$.tags[1]"])

    def test_array_length_is_limited(self) -> None:
        self.assertEqual(
            issue_paths({"city": "北京", "tags": ["a", "b", "c"]}),
            ["$.tags"],
        )

    def test_all_issues_are_reported_together(self) -> None:
        self.assertEqual(
            sorted(issue_paths({"days": 30})),
            ["$.city", "$.days"],
        )


if __name__ == "__main__":
    unittest.main()