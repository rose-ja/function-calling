import unittest

from tool_schema import validate_arguments


SCHEMA = {
    "type": "object",
    "properties": {
        "city": {"type": "string", "minLength": 1, "pattern": r"\S"},
        "days": {"type": "integer", "minimum": 1, "maximum": 7},
    },
    "required": ["city"],
    "additionalProperties": False,
}


def issue_paths(arguments: object) -> list[str]:
    return [issue.path for issue in validate_arguments(SCHEMA, arguments)]


class SchemaValidationTests(unittest.TestCase):
    def test_valid_arguments_pass(self) -> None:
        self.assertEqual(validate_arguments(SCHEMA, {"city": "北京", "days": 3}), [])

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

    def test_all_issues_are_reported_together(self) -> None:
        self.assertEqual(
            sorted(issue_paths({"days": 30})),
            ["$.city", "$.days"],
        )


if __name__ == "__main__":
    unittest.main()