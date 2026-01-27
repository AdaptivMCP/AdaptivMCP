from __future__ import annotations

import base64
from typing import Any

import pytest

import extra_tools


@pytest.mark.anyio
async def test_delete_file_rejects_invalid_if_missing() -> None:
    with pytest.raises(ValueError, match="if_missing must be 'error' or 'noop'"):
        await extra_tools.delete_file(
            full_name="octo-org/octo-repo",
            path="README.md",
            if_missing="bad",  # type: ignore[arg-type]
        )


@pytest.mark.anyio
async def test_delete_file_returns_noop_when_missing_and_if_missing_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(extra_tools, "_effective_ref_for_repo", lambda _n, b: b)
    monkeypatch.setattr(extra_tools, "_normalize_repo_path_for_repo", lambda _n, p: p)

    async def fake_resolve(*_args: Any, **_kwargs: Any) -> str | None:
        return None

    monkeypatch.setattr(extra_tools, "_resolve_file_sha", fake_resolve)

    result = await extra_tools.delete_file(
        full_name="octo-org/octo-repo",
        path="docs/missing.txt",
        branch="main",
        if_missing="noop",
    )

    assert result == {
        "status": "noop",
        "full_name": "octo-org/octo-repo",
        "path": "docs/missing.txt",
        "branch": "main",
    }


@pytest.mark.anyio
async def test_delete_file_raises_when_missing_and_if_missing_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(extra_tools, "_effective_ref_for_repo", lambda _n, b: b)
    monkeypatch.setattr(extra_tools, "_normalize_repo_path_for_repo", lambda _n, p: p)

    async def fake_resolve(*_args: Any, **_kwargs: Any) -> str | None:
        return None

    monkeypatch.setattr(extra_tools, "_resolve_file_sha", fake_resolve)

    with pytest.raises(FileNotFoundError, match=r"File not found: docs/missing.txt on main"):
        await extra_tools.delete_file(
            full_name="octo-org/octo-repo",
            path="docs/missing.txt",
            branch="main",
            if_missing="error",
        )


@pytest.mark.anyio
async def test_delete_file_calls_github_request_with_expected_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(extra_tools, "_effective_ref_for_repo", lambda _n, b: b)
    monkeypatch.setattr(extra_tools, "_normalize_repo_path_for_repo", lambda _n, p: p)

    async def fake_resolve(*_args: Any, **_kwargs: Any) -> str | None:
        return "deadbeef"

    monkeypatch.setattr(extra_tools, "_resolve_file_sha", fake_resolve)

    calls: list[dict[str, Any]] = []

    async def fake_request(method: str, endpoint: str, **kwargs: Any) -> dict[str, Any]:
        calls.append({"method": method, "endpoint": endpoint, **kwargs})
        return {"ok": True, "commit": {"sha": "c0ffee"}}

    monkeypatch.setattr(extra_tools, "_github_request", fake_request)

    result = await extra_tools.delete_file(
        full_name="octo-org/octo-repo",
        path="docs/file.txt",
        branch="main",
        message="delete it",
    )

    assert result["status"] == "deleted"
    assert result["path"] == "docs/file.txt"
    assert result["branch"] == "main"
    assert result["commit"] == {"ok": True, "commit": {"sha": "c0ffee"}}

    assert len(calls) == 1
    assert calls[0]["method"] == "DELETE"
    assert calls[0]["endpoint"] == "/repos/octo-org/octo-repo/contents/docs/file.txt"
    assert calls[0]["expect_json"] is True
    assert calls[0]["json_body"] == {
        "message": "delete it",
        "sha": "deadbeef",
        "branch": "main",
    }


@pytest.mark.anyio
async def test_update_file_from_workspace_rejects_path_escape(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(extra_tools, "_effective_ref_for_repo", lambda _n, b: b)
    monkeypatch.setattr(extra_tools, "_workspace_path", lambda _n, _r: str(tmp_path))

    with pytest.raises(ValueError, match="workspace_path must stay within the workspace root"):
        await extra_tools.update_file_from_workspace(
            full_name="octo-org/octo-repo",
            workspace_path="../outside.txt",
            target_path="docs/outside.txt",
            branch="main",
            message="update",
        )


@pytest.mark.anyio
async def test_update_file_from_workspace_raises_when_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(extra_tools, "_effective_ref_for_repo", lambda _n, b: b)
    monkeypatch.setattr(extra_tools, "_workspace_path", lambda _n, _r: str(tmp_path))

    with pytest.raises(FileNotFoundError, match=r"Repo mirror file 'missing.txt' not found"):
        await extra_tools.update_file_from_workspace(
            full_name="octo-org/octo-repo",
            workspace_path="missing.txt",
            target_path="docs/missing.txt",
            branch="main",
            message="update",
        )


@pytest.mark.anyio
async def test_update_file_from_workspace_puts_content_and_omits_sha_when_creating(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(extra_tools, "_effective_ref_for_repo", lambda _n, b: b)
    monkeypatch.setattr(extra_tools, "_workspace_path", lambda _n, _r: str(tmp_path))
    monkeypatch.setattr(extra_tools, "_normalize_repo_path_for_repo", lambda _n, p: p)

    data = b"\x00\x01hello"
    (tmp_path / "payload.bin").write_bytes(data)

    async def fake_resolve(*_args: Any, **_kwargs: Any) -> str | None:
        return None

    monkeypatch.setattr(extra_tools, "_resolve_file_sha", fake_resolve)

    seen: dict[str, Any] = {}

    async def fake_request(method: str, endpoint: str, **kwargs: Any) -> dict[str, Any]:
        seen.update({"method": method, "endpoint": endpoint, **kwargs})
        return {"ok": True}

    monkeypatch.setattr(extra_tools, "_github_request", fake_request)

    result = await extra_tools.update_file_from_workspace(
        full_name="octo-org/octo-repo",
        workspace_path="payload.bin",
        target_path="docs/payload.bin",
        branch="main",
        message="add payload",
    )

    assert result["workspace_path"] == "payload.bin"
    assert result["target_path"] == "docs/payload.bin"

    assert seen["method"] == "PUT"
    assert seen["endpoint"] == "/repos/octo-org/octo-repo/contents/docs/payload.bin"

    payload = seen["json_body"]
    assert payload["message"] == "add payload"
    assert payload["branch"] == "main"
    assert payload["content"] == base64.b64encode(data).decode("ascii")
    assert "sha" not in payload


@pytest.mark.anyio
async def test_update_file_from_workspace_includes_sha_when_updating(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(extra_tools, "_effective_ref_for_repo", lambda _n, b: b)
    monkeypatch.setattr(extra_tools, "_workspace_path", lambda _n, _r: str(tmp_path))
    monkeypatch.setattr(extra_tools, "_normalize_repo_path_for_repo", lambda _n, p: p)

    (tmp_path / "payload.txt").write_text("hello")

    async def fake_resolve(*_args: Any, **_kwargs: Any) -> str | None:
        return "abc123"

    monkeypatch.setattr(extra_tools, "_resolve_file_sha", fake_resolve)

    async def fake_request(_method: str, _endpoint: str, **kwargs: Any) -> dict[str, Any]:
        return {"ok": True, "payload": kwargs["json_body"]}

    monkeypatch.setattr(extra_tools, "_github_request", fake_request)

    result = await extra_tools.update_file_from_workspace(
        full_name="octo-org/octo-repo",
        workspace_path="payload.txt",
        target_path="docs/payload.txt",
        branch="main",
        message="update payload",
    )

    assert result["commit"]["payload"]["sha"] == "abc123"


@pytest.mark.anyio
async def test_update_file_from_workspace_allows_absolute_path_inside_workspace_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(extra_tools, "_effective_ref_for_repo", lambda _n, b: b)
    monkeypatch.setattr(extra_tools, "_workspace_path", lambda _n, _r: str(tmp_path))
    monkeypatch.setattr(extra_tools, "_normalize_repo_path_for_repo", lambda _n, p: p)

    subdir = tmp_path / "sub"
    subdir.mkdir()
    fpath = subdir / "a.txt"
    fpath.write_text("hello")

    async def fake_resolve(*_args: Any, **_kwargs: Any) -> str | None:
        return None

    monkeypatch.setattr(extra_tools, "_resolve_file_sha", fake_resolve)

    async def fake_request(_method: str, _endpoint: str, **_kwargs: Any) -> dict[str, Any]:
        return {"ok": True}

    monkeypatch.setattr(extra_tools, "_github_request", fake_request)

    result = await extra_tools.update_file_from_workspace(
        full_name="octo-org/octo-repo",
        workspace_path=str(fpath),
        target_path="docs/a.txt",
        branch="main",
        message="add",
    )

    assert result["workspace_path"] == "sub/a.txt"
