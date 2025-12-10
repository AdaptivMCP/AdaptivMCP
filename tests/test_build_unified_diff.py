import asyncio

import pytest

import main


async def _fake_decode(full_name: str, path: str, ref: str = "main") -> dict:
    base_text = "alpha \n\tbeta\n"
    return {
        "text": base_text,
        "numbered_lines": main._with_numbered_lines(base_text),
    }


def test_build_unified_diff_includes_visible_whitespace(monkeypatch):
    monkeypatch.setattr(main, "_decode_github_content", _fake_decode)

    result = asyncio.run(
        main.build_unified_diff(
            "owner/repo",
            "path.txt",
            new_content="alpha\n\tbeta!\n",
            context_lines=1,
            show_whitespace=True,
        )
    )

    assert result["path"] == "path.txt"
    assert result["diff"].startswith("--- a/path.txt")
    assert "visible_whitespace" in result
    assert "·" in result["visible_whitespace"]["base"]
    assert "→" in result["visible_whitespace"]["base"]
    assert result["proposed"]["numbered_lines"][0]["text"] == "alpha"


def test_build_unified_diff_rejects_negative_context(monkeypatch):
    monkeypatch.setattr(main, "_decode_github_content", _fake_decode)

    with pytest.raises(ValueError):
        asyncio.run(
            main.build_unified_diff("owner/repo", "path.txt", new_content="alpha", context_lines=-1)
        )


@pytest.mark.asyncio
async def test_build_unified_diff_whitespace_only_change(monkeypatch):
    async def _fake_decode_ws(full_name, path, ref="main"):
        base_text = "alpha\n"
        return {"text": base_text, "numbered_lines": main._with_numbered_lines(base_text)}

    monkeypatch.setattr(main, "_decode_github_content", _fake_decode_ws)

    result = await main.build_unified_diff(
        "owner/repo",
        "file.txt",
        new_content="alpha \n",  # only whitespace change
        context_lines=3,
        show_whitespace=True,
    )

    diff = result["diff"]
    assert diff
    assert diff.startswith("--- a/file.txt")
    assert "+alpha " in diff
    assert "-alpha\n" in diff

    visible = result["visible_whitespace"]
    assert "base" in visible
    assert "⏎" in visible["base"]


@pytest.mark.asyncio
async def test_build_unified_diff_zero_context_has_no_context_lines(monkeypatch):
    async def _fake_decode_zero(full_name, path, ref="main"):
        base_text = "one\nTWO\nthree\n"
        return {"text": base_text, "numbered_lines": main._with_numbered_lines(base_text)}

    monkeypatch.setattr(main, "_decode_github_content", _fake_decode_zero)

    result = await main.build_unified_diff(
        "owner/repo",
        "file.txt",
        new_content="one\nTWO!\nthree\n",
        context_lines=0,
        show_whitespace=False,
    )

    assert result["context_lines"] == 0
    diff = result["diff"]
    assert diff.startswith("--- a/file.txt")

    for line in diff.splitlines():
        if not line or line.startswith(("---", "+++", "@@")):
            continue
        assert not line.startswith(" ")


@pytest.mark.asyncio
async def test_build_unified_diff_from_empty_file(monkeypatch):
    async def _fake_decode_empty(full_name, path, ref="main"):
        base_text = ""
        return {"text": base_text, "numbered_lines": main._with_numbered_lines(base_text)}

    monkeypatch.setattr(main, "_decode_github_content", _fake_decode_empty)

    result = await main.build_unified_diff(
        "owner/repo",
        "empty.txt",
        new_content="hello\nworld\n",
        context_lines=2,
        show_whitespace=False,
    )

    diff = result["diff"]
    assert diff
    assert diff.startswith("--- a/empty.txt")
    assert "+hello" in diff
    assert "+world" in diff
