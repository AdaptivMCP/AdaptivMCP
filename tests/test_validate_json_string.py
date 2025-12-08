import main


def test_validate_json_string_success():
    payload = '{"z": 2, "a": [1, 2], "name": "ally"}'

    result = main.validate_json_string(payload)

    assert result["valid"] is True
    assert result["parsed"] == {"a": [1, 2], "name": "ally", "z": 2}
    # normalized output should be compact and sorted for predictable reuse
    assert result["normalized"] == '{"a":[1,2],"name":"ally","z":2}'
    assert (
        result["normalized_pretty"]
        == '{\n  "a": [\n    1,\n    2\n  ],\n  "name": "ally",\n  "z": 2\n}'
    )
    assert result["parsed_type"] == "dict"


def test_validate_json_string_failure_reports_context():
    payload = '{"a": 1 trailing}'

    result = main.validate_json_string(payload)

    assert result["valid"] is False
    assert "error" in result
    assert result["line"] == 1
    assert result["column"] > 0
    assert "snippet" in result
    assert "line_snippet" in result
    assert "pointer" in result
    assert "trailing" in result["snippet"]
