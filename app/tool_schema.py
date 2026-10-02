from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ValidationIssue:
    path: str
    message: str

    def describe(self) -> str:
        return f"{self.path} {self.message}"


def validate_arguments(schema: Any, arguments: Any) -> list[ValidationIssue]:
    """按 JSON Schema 子集校验参数，返回全部问题而不是遇到第一个就中断。"""
    if not isinstance(schema, dict):
        return []

    issues: list[ValidationIssue] = []
    _validate_node(schema, arguments, "$", issues)
    return issues


def _matches_json_type(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        # bool 是 int 的子类，必须显式排除，否则 True 会被当作合法整数。
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "null":
        return value is None
    return True


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _join(path: str, field_name: str) -> str:
    return f"{path}.{field_name}"


def _validate_node(
    schema: Any,
    value: Any,
    path: str,
    issues: list[ValidationIssue],
) -> None:
    if not isinstance(schema, dict):
        return

    expected_type = schema.get("type")
    if isinstance(expected_type, str) and not _matches_json_type(value, expected_type):
        issues.append(ValidationIssue(path, f"类型必须是 {expected_type}"))
        return

    enum_values = schema.get("enum")
    if isinstance(enum_values, list) and enum_values and value not in enum_values:
        issues.append(ValidationIssue(path, f"取值必须是 {enum_values} 之一"))
        return

    if isinstance(value, dict):
        _validate_object(schema, value, path, issues)
    elif isinstance(value, str):
        _validate_string(schema, value, path, issues)
    elif _is_number(value):
        _validate_number(schema, value, path, issues)
    elif isinstance(value, list):
        _validate_array(schema, value, path, issues)


def _validate_object(
    schema: dict[str, Any],
    value: dict[str, Any],
    path: str,
    issues: list[ValidationIssue],
) -> None:
    properties = schema.get("properties")
    properties = properties if isinstance(properties, dict) else {}

    required = schema.get("required")
    required = required if isinstance(required, list) else []

    for field_name in required:
        if isinstance(field_name, str) and field_name not in value:
            issues.append(ValidationIssue(_join(path, field_name), "字段缺失"))

    for field_name, field_value in value.items():
        field_schema = properties.get(field_name)
        child_path = _join(path, field_name)

        if field_schema is None:
            if schema.get("additionalProperties") is False:
                issues.append(ValidationIssue(child_path, "不允许的字段"))
            continue

        _validate_node(field_schema, field_value, child_path, issues)


def _validate_string(
    schema: dict[str, Any],
    value: str,
    path: str,
    issues: list[ValidationIssue],
) -> None:
    min_length = schema.get("minLength")
    if isinstance(min_length, int) and not isinstance(min_length, bool):
        if len(value) < min_length:
            issues.append(ValidationIssue(path, f"长度不能小于 {min_length}"))

    max_length = schema.get("maxLength")
    if isinstance(max_length, int) and not isinstance(max_length, bool):
        if len(value) > max_length:
            issues.append(ValidationIssue(path, f"长度不能大于 {max_length}"))

    pattern = schema.get("pattern")
    if isinstance(pattern, str):
        try:
            matched = re.search(pattern, value) is not None
        except re.error:
            # Schema 自身的正则写错属于配置问题，不应改写成参数错误。
            return
        if not matched:
            issues.append(ValidationIssue(path, "格式不符合要求"))


def _validate_number(
    schema: dict[str, Any],
    value: int | float,
    path: str,
    issues: list[ValidationIssue],
) -> None:
    minimum = schema.get("minimum")
    if _is_number(minimum) and value < minimum:
        issues.append(ValidationIssue(path, f"不能小于 {minimum}"))

    maximum = schema.get("maximum")
    if _is_number(maximum) and value > maximum:
        issues.append(ValidationIssue(path, f"不能大于 {maximum}"))


def _validate_array(
    schema: dict[str, Any],
    value: list[Any],
    path: str,
    issues: list[ValidationIssue],
) -> None:
    min_items = schema.get("minItems")
    if isinstance(min_items, int) and not isinstance(min_items, bool):
        if len(value) < min_items:
            issues.append(ValidationIssue(path, f"元素个数不能少于 {min_items}"))

    max_items = schema.get("maxItems")
    if isinstance(max_items, int) and not isinstance(max_items, bool):
        if len(value) > max_items:
            issues.append(ValidationIssue(path, f"元素个数不能多于 {max_items}"))

    item_schema = schema.get("items")
    if isinstance(item_schema, dict):
        for index, item in enumerate(value):
            _validate_node(item_schema, item, f"{path}[{index}]", issues)