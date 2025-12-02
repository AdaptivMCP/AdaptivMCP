import json

import pytest

import main


def test_normalize_args_keeps_mapping_and_multiline_commands():
    raw_args = {
        "full_name": "owner/repo",
        "ref": "feature-branch",
        "command": "python - <<'EOF'\nprint('line 1')\nprint('line 2')\nEOF\n",
    }

    normalized = main.normalize_args(raw_args)

    assert normalized == raw_args


def test_normalize_args_parses_json_strings_when_object():
    raw_args = json.dumps({"full_name": "owner/repo", "command": "echo hi"})

    normalized = main.normalize_args(raw_args)

    assert normalized == {"full_name": "owner/repo", "command": "echo hi"}


def test_normalize_args_rejects_invalid_json_string():
    with pytest.raises(ValueError) as excinfo:
        main.normalize_args("{invalid json")

    assert "args must be a valid JSON object/array" in str(excinfo.value)


def test_normalize_args_rejects_non_mapping_text():
    with pytest.raises(TypeError):
        main.normalize_args("echo hi")


def test_normalize_args_rejects_arrays():
    with pytest.raises(TypeError):
        main.normalize_args("[1, 2, 3]")
