from __future__ import annotations

import json

from dispatcher import TOOL_REGISTRY, dispatch_tool


def main() -> None:
    for spec in TOOL_REGISTRY.values():
        print(
            f"{spec.name:<14} risk={spec.risk_level} "
            f"confirm={spec.requires_confirmation} "
            f"timeout={spec.timeout_seconds}s "
            f"retry_on_timeout={spec.retryable_on_timeout}"
        )

    print("\n--- 提供给模型的工具契约 ---")
    print(
        json.dumps(
            TOOL_REGISTRY["get_weather"].to_model_schema(),
            ensure_ascii=False,
            indent=2,
        )
    )

    print("\n--- 模拟模型提出的调用（不可信输入）---")
    raw_model_outputs = [
        {"tool_name": "get_weather", "arguments": {"city": "北京"}},
        {"tool_name": "get_weather", "arguments": {"city": " 上海 "}},
        {"tool_name": "get_weather", "arguments": {"city": "广州"}},
        {"tool_name": "get_weather", "arguments": {"city": ""}},
        {"tool_name": "get_weather", "arguments": {"city": "北京", "force": True}},
        {"tool_name": "get_weather", "arguments": ["北京"]},
        {"tool_name": "search_weather", "arguments": {"city": "北京"}},
        {"tool_name": None, "arguments": {}},
    ]

    for model_output in raw_model_outputs:
        result = dispatch_tool(
            model_output["tool_name"],
            model_output["arguments"],
        )
        if result.status == "success":
            print(f"OK    {model_output['tool_name']}  {result.data}")
        else:
            print(
                f"FAIL  {result.error.type.value:<20} "
                f"{result.error.execution_state.value:<12} {result.error.message}"
            )


if __name__ == "__main__":
    main()