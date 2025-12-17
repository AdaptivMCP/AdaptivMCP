import pytest

import extra_tools

# Local registry to capture tools registered via register_extra_tools
_TOOL_REGISTRY: dict[str, object] = {}


def _capture_tool(*, write_action: bool = False, **tool_kwargs):  # type: ignore[override]
    def decorator(fn):
        _TOOL_REGISTRY[fn.__name__] = fn
        return fn

    return decorator


# Register the extra tools using the capture decorator so we can call them directly.
extra_tools.register_extra_tools(_capture_tool)
GET_FILE_WITH_LINE_NUMBERS = _TOOL_REGISTRY["get_file_with_line_numbers"]


@pytest.mark.asyncio
async def test_get_file_with_line_numbers(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}

    def fake_effective_ref(full_name: str, ref: str | None) -> str:
        calls["effective_full_name"] = full_name
        calls["effective_ref_param"] = ref
        return "ally-refactor"

    async def fake_decode(full_name: str, path: str, ref: str | None):
        calls["decode_full_name"] = full_name
        calls["decode_path"] = path
        calls["decode_ref"] = ref
        return {"text": "alpha\nbeta\ngamma"}

    monkeypatch.setattr(extra_tools, "_effective_ref_for_repo", fake_effective_ref)
    monkeypatch.setattr(extra_tools, "_decode_github_content", fake_decode)

    result = await GET_FILE_WITH_LINE_NUMBERS(
        full_name="owner/repo",
        path="dir/file.txt",
        ref=None,
        start_line=2,
        max_lines=2,
    )

    assert result["full_name"] == "owner/repo"
    assert result["path"] == "dir/file.txt"
    assert result["ref"] == "ally-refactor"
    assert result["start_line"] == 2
    assert result["end_line"] == 3
    assert result["total_lines"] == 3
    assert result["has_more_above"] is True
    assert result["has_more_below"] is False
    assert result["lines"] == [
        {"line": 2, "text": "beta"},
        {"line": 3, "text": "gamma"},
    ]
    assert result["numbered_text"].splitlines() == ["2| beta", "3| gamma"]

    # Ensure the helpers were called with the original parameters so ref mapping works.
    assert calls["effective_full_name"] == "owner/repo"
    assert calls["effective_ref_param"] is None
    assert calls["decode_full_name"] == "owner/repo"
    assert calls["decode_path"] == "dir/file.txt"
    assert calls["decode_ref"] == "ally-refactor"


@pytest.mark.asyncio
async def test_get_file_with_line_numbers_empty_file(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_decode(full_name: str, path: str, ref: str | None):
        return {"text": ""}

    monkeypatch.setattr(extra_tools, "_effective_ref_for_repo", lambda full_name, ref: "main")
    monkeypatch.setattr(extra_tools, "_decode_github_content", fake_decode)

    result = await GET_FILE_WITH_LINE_NUMBERS(
        full_name="owner/repo",
        path="empty.txt",
    )

    assert result["total_lines"] == 0
    assert result["lines"] == []
    assert result["numbered_text"] == ""
    assert result["start_line"] == 1
    assert result["end_line"] == 0
    assert result["has_more_above"] is False
    assert result["has_more_below"] is False


@pytest.mark.asyncio
async def test_get_file_with_line_numbers_default_bounds(monkeypatch: pytest.MonkeyPatch) -> None:
    # 400-line file; default should return a bounded slice (200 lines).
    sample = "\n".join([f"line{i}" for i in range(1, 401)])

    async def fake_decode(full_name: str, path: str, ref: str | None):
        return {"text": sample}

    monkeypatch.setattr(extra_tools, "_effective_ref_for_repo", lambda full_name, ref: "main")
    monkeypatch.setattr(extra_tools, "_decode_github_content", fake_decode)

    result = await GET_FILE_WITH_LINE_NUMBERS(
        full_name="owner/repo",
        path="big.txt",
    )

    assert result["start_line"] == 1
    assert result["end_line"] == 200
    assert result["total_lines"] == 400
    assert result["has_more_below"] is True
    assert result["truncated"] is False
    assert len(result["lines"]) == 200


@pytest.mark.asyncio
async def test_get_file_with_line_numbers_max_chars_truncates(monkeypatch: pytest.MonkeyPatch) -> None:
    sample = "\n".join(["x" * 40 for _ in range(50)])

    async def fake_decode(full_name: str, path: str, ref: str | None):
        return {"text": sample}

    monkeypatch.setattr(extra_tools, "_effective_ref_for_repo", lambda full_name, ref: "main")
    monkeypatch.setattr(extra_tools, "_decode_github_content", fake_decode)

    result = await GET_FILE_WITH_LINE_NUMBERS(
        full_name="owner/repo",
        path="wide.txt",
        max_lines=50,
        max_chars=120,
    )

    assert result["truncated"] is True
    assert result["has_more_below"] in (True, False)
    assert result["numbered_text"].endswith("… (truncated)")
