from __future__ import annotations

from typing import Any

import pytest

from github_mcp import llm_tool_calls


def test_coerce_json_round_trips_and_is_conservative() -> None:
    # Non-strings should pass through.
    assert llm_tool_calls._coerce_json({"a": 1}) == {"a": 1}
    assert llm_tool_calls._coerce_json(123) == 123

    # Empty/whitespace strings should pass through.
    assert llm_tool_calls._coerce_json("") == ""
    assert llm_tool_calls._coerce_json("   ") == "   "

    # Non-JSON looking strings should pass through.
    assert llm_tool_calls._coerce_json("hello") == "hello"

    # JSON objects/lists should parse.
    assert llm_tool_calls._coerce_json('{"a": 1}') == {"a": 1}
    assert llm_tool_calls._coerce_json("[1, 2]") == [1, 2]

    # Invalid JSON should pass through.
    assert llm_tool_calls._coerce_json("{not-json}") == "{not-json}"


def test_normalize_call_object_openai_wrapper_and_common_shapes() -> None:
    payload: dict[str, Any] = {
        "tool_calls": [
            {"function": {"name": "foo", "arguments": '{"x": 1}'}},
            {"function": {"name": "bar", "arguments": {"y": 2}}},
            {"function": {}},
            "not-a-dict",
            {"tool": "baz", "args": {"z": 3}},
        ]
    }

    assert llm_tool_calls._normalize_call_object(payload) == [
        ("foo", {"x": 1}),
        ("bar", {"y": 2}),
        ("baz", {"z": 3}),
    ]


def test_normalize_call_object_function_dict_fallback_and_list_coercion() -> None:
    # When the object has a function dict but no name/tool at the top level.
    # If arguments decode to a non-dict, args should be {}.
    assert llm_tool_calls._normalize_call_object(
        {"function": {"name": "qux", "arguments": "[1, 2]"}}
    ) == [("qux", {})]


def test_normalize_call_object_args_precedence_and_recursive_lists() -> None:
    # args should win over other arg-ish keys.
    assert llm_tool_calls._normalize_call_object(
        {"name": "t", "args": {"a": 1}, "arguments": {"a": 2}}
    ) == [("t", {"a": 1})]

    # parameters should be accepted.
    assert llm_tool_calls._normalize_call_object(
        {"tool_name": "p", "parameters": {"k": 9}}
    ) == [("p", {"k": 9})]

    # Lists should be flattened and non-dict entries ignored.
    assert llm_tool_calls._normalize_call_object(
        [None, {"name": "t2", "args": {"b": 2}}]
    ) == [("t2", {"b": 2})]


def test_extract_tool_calls_from_text_filters_and_positions() -> None:
    text = (
        "prefix\n"
        '```python\n{"tool": "ignored", "args": {}}\n```\n'
        '```json\n{"tool": "alpha", "args": {"x": 1}}\n```\n'
        "```\nnot-json\n```\n"
        '```tool\n{"tool_calls": [{"function": {"name": "beta", "arguments": "{\\"y\\": 2}"}}]}\n```\n'
        "suffix"
    )

    calls = llm_tool_calls.extract_tool_calls_from_text(
        [("assistant", text), ("tool", None)]
    )

    assert [(c.tool_name, c.args, c.channel) for c in calls] == [
        ("alpha", {"x": 1}, "assistant"),
        ("beta", {"y": 2}, "assistant"),
    ]

    # Ensure the position metadata maps back onto the original string.
    for call in calls:
        assert 0 <= call.start < call.end <= len(text)
        snippet = text[call.start : call.end]
        assert snippet.startswith("```")
        assert snippet.endswith("```")


def test_extract_tool_calls_respects_max_calls() -> None:
    text = (
        '```json\n{"tool": "a", "args": {}}\n```\n'
        '```json\n{"tool": "b", "args": {}}\n```\n'
        '```json\n{"tool": "c", "args": {}}\n```\n'
    )

    calls = llm_tool_calls.extract_tool_calls_from_text(
        [("assistant", text)], max_calls=1
    )
    assert [c.tool_name for c in calls] == ["a"]


@pytest.mark.parametrize(
    "lang",
    [
        "tool",
        "tools",
        "mcp",
        "tool_call",
        "toolcall",
        "action",
        "json",
        "",  # empty lang is allowed as long as the body is JSON-ish
    ],
)
def test_extract_tool_calls_accepts_whitelisted_languages(lang: str) -> None:
    fence = f'```{lang}\n{{"tool": "x", "args": {{"n": 1}}}}\n```'
    calls = llm_tool_calls.extract_tool_calls_from_text([("assistant", fence)])
    assert len(calls) == 1
    assert calls[0].tool_name == "x"
    assert calls[0].args == {"n": 1}


def test_extract_file_blocks_from_text_and_resolve_references() -> None:
    text = (
        "prefix\n"
        "```file\n"
        "path: foo/bar.txt\n"
        "name: bar\n"
        "\n"
        "line1\n"
        "line2\n"
        "```\n"
        "```json\n"
        '{"tool": "set_workspace_file_contents", "args": {"path": "foo/bar.txt", "content": "@file:foo/bar.txt"}}\n'
        "```\n"
        "suffix"
    )

    blocks = llm_tool_calls.extract_file_blocks_from_text([("assistant", text)])
    assert blocks["foo/bar.txt"].strip() == "line1\nline2"
    assert blocks["bar"].strip() == "line1\nline2"

    calls = llm_tool_calls.extract_tool_calls_from_text([("assistant", text)])
    assert len(calls) == 1
    resolved = llm_tool_calls.resolve_block_references(calls[0].args, blocks)
    assert resolved["content"].strip() == "line1\nline2"


def test_resolve_block_references_supports_dict_sentinel_form() -> None:
    blocks = {"x": "CONTENT"}
    payload = {"a": {"$file": "x"}, "b": [{"$block": "x"}]}
    resolved = llm_tool_calls.resolve_block_references(payload, blocks)
    assert resolved == {"a": "CONTENT", "b": ["CONTENT"]}
