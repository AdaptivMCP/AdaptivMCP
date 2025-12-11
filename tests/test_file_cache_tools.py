import pytest

import main


@pytest.mark.asyncio
async def test_cache_files_reuses_cached_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    main._reset_file_cache_for_tests()

    decode_calls: list[tuple[str, str, str | None]] = []

    async def fake_decode(full_name: str, path: str, ref: str | None):
        decode_calls.append((full_name, path, ref))
        body = f"body-{path}"
        return {"text": body, "decoded_bytes": body.encode(), "json": {"sha": f"sha-{path}"}}

    monkeypatch.setattr(main, "_decode_github_content", fake_decode)

    first = await main.cache_files("owner/repo", paths=["src/a.txt"], ref="dev")
    assert first["files"]["src/a.txt"]["text"] == "body-src/a.txt"
    assert first["files"]["src/a.txt"]["cached"] is False
    assert first["ref"] == "dev"
    assert len(decode_calls) == 1

    second = await main.cache_files("owner/repo", paths=["src/a.txt"], ref="dev")
    assert second["files"]["src/a.txt"]["text"] == "body-src/a.txt"
    assert second["files"]["src/a.txt"]["cached"] is True
    assert len(decode_calls) == 1  # cache hit, no new decode

    refreshed = await main.cache_files("owner/repo", paths=["src/a.txt"], ref="dev", refresh=True)
    assert refreshed["files"]["src/a.txt"]["cached"] is False
    assert len(decode_calls) == 2


@pytest.mark.asyncio
async def test_get_cached_files_returns_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    main._reset_file_cache_for_tests()

    async def fake_decode(full_name: str, path: str, ref: str | None):
        return {"text": f"content-{path}", "decoded_bytes": b"content", "json": {"sha": "abc"}}

    monkeypatch.setattr(main, "_decode_github_content", fake_decode)
    await main.cache_files("owner/repo", paths=["dir/keep.txt"], ref="main")

    cached = await main.get_cached_files(
        full_name="owner/repo",
        paths=["dir/keep.txt", "dir/missing.txt"],
        ref="main",
    )

    assert set(cached["files"].keys()) == {"dir/keep.txt"}
    assert cached["files"]["dir/keep.txt"]["text"] == "content-dir/keep.txt"
    assert cached["missing"] == ["dir/missing.txt"]
