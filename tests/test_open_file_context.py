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
OPEN_FILE_CONTEXT = _TOOL_REGISTRY["open_file_context"]


@pytest.mark.asyncio
async def test_open_file_context_uses_range(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}

    def fake_effective_ref(full_name: str, ref: str | None) -> str:
        calls["effective_full_name"] = full_name
        calls["effective_ref_param"] = ref
        return "effective-ref"

    async def fake_decode(full_name: str, path: str, ref: str | None):
        calls.setdefault("decode_calls", []).append((full_name, path, ref))
        return {"text": "alpha\nbeta\ngamma\ndelta"}

    monkeypatch.setattr(extra_tools, "_effective_ref_for_repo", fake_effective_ref)
    monkeypatch.setattr(extra_tools, "_decode_github_content", fake_decode)

    result = await OPEN_FILE_CONTEXT(
        full_name="owner/repo",
        path="dir/file.txt",
        ref="ally-refactor",
        start_line=2,
        max_lines=2,
    )

    assert result["full_name"] == "owner/repo"
    assert result["path"] == "dir/file.txt"
    assert result["ref"] == "effective-ref"
    assert result["start_line"] == 2
    assert result["end_line"] == 3
    assert result["total_lines"] == 4
    assert result["has_more_above"] is True
    assert result["has_more_below"] is True
    assert result["content"] == [
        {"line": 2, "text": "beta"},
        {"line": 3, "text": "gamma"},
    ]

    assert calls["effective_full_name"] == "owner/repo"
    assert calls["effective_ref_param"] == "ally-refactor"
    assert calls["decode_calls"] == [("owner/repo", "dir/file.txt", "effective-ref")]


@pytest.mark.asyncio
async def test_open_file_context_expands_small_files(monkeypatch: pytest.MonkeyPatch) -> None:
    decode_calls = 0

    monkeypatch.setattr(extra_tools, "_effective_ref_for_repo", lambda full_name, ref: "main")

    async def fake_decode(full_name: str, path: str, ref: str | None):
        nonlocal decode_calls
        decode_calls += 1
        return {"text": "\n".join(f"line-{i}" for i in range(1, 6))}

    monkeypatch.setattr(extra_tools, "_decode_github_content", fake_decode)

    result = await OPEN_FILE_CONTEXT(
        full_name="owner/repo",
        path="src/tiny.txt",
        start_line=1,
        max_lines=2,
    )

    assert result["start_line"] == 1
    assert result["end_line"] == 5
    assert result["total_lines"] == 5
    assert len(result["content"]) == 5
    assert result.get("note", "").startswith("File is small")
    assert decode_calls == 2  # small files are expanded via a second slice


@pytest.mark.asyncio
async def test_open_file_context_handles_range_near_end(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(extra_tools, "_effective_ref_for_repo", lambda full_name, ref: "main")

    async def fake_decode(full_name: str, path: str, ref: str | None):
        return {"text": "\n".join(f"line-{i}" for i in range(1, 101))}

    monkeypatch.setattr(extra_tools, "_decode_github_content", fake_decode)

    result = await OPEN_FILE_CONTEXT(
        full_name="owner/repo",
        path="src/file.py",
        start_line=95,
        max_lines=20,
    )

    assert result["start_line"] == 95
    assert result["end_line"] == 100
    assert result["has_more_below"] is False
    assert result["content"][0]["line"] == 95
    assert result["content"][-1]["line"] == 100
