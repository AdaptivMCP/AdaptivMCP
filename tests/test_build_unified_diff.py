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
