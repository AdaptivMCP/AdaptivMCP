import pytest

import main


@pytest.mark.asyncio
async def test_create_repository_user_repo_defaults_to_user_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    async def fake_github_request(method: str, path: str, **kwargs):
        calls.append((method, path, kwargs.get("json_body"), kwargs.get("headers")))
        if method == "GET" and path == "/user":
            return {"json": {"login": "me"}}
        if method == "POST" and path == "/user/repos":
            body = kwargs.get("json_body") or {}
            assert body["name"] == "demo"
            assert body["auto_init"] is True
            return {"status_code": 201, "json": {"full_name": "me/demo"}}
        raise AssertionError(f"unexpected call: {method} {path}")

    monkeypatch.setattr(main, "_github_request", fake_github_request)
    monkeypatch.setattr(main, "_ensure_write_allowed", lambda *_a, **_k: None)

    result = await main.create_repository(name="demo")

    assert result["full_name"] == "me/demo"
    assert calls[0][:2] == ("GET", "/user")
    assert calls[1][:2] == ("POST", "/user/repos")


@pytest.mark.asyncio
async def test_create_repository_org_owner_uses_org_endpoint_when_auto(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    async def fake_github_request(method: str, path: str, **kwargs):
        calls.append((method, path, kwargs.get("json_body"), kwargs.get("headers")))
        if method == "GET" and path == "/user":
            return {"json": {"login": "me"}}
        if method == "POST" and path == "/orgs/acme/repos":
            body = kwargs.get("json_body") or {}
            assert body["name"] == "demo"
            return {"status_code": 201, "json": {"full_name": "acme/demo"}}
        raise AssertionError(f"unexpected call: {method} {path}")

    monkeypatch.setattr(main, "_github_request", fake_github_request)
    monkeypatch.setattr(main, "_ensure_write_allowed", lambda *_a, **_k: None)

    result = await main.create_repository(name="demo", owner="acme", owner_type="auto")

    assert result["full_name"] == "acme/demo"
    assert ("POST", "/orgs/acme/repos") in [(c[0], c[1]) for c in calls]


@pytest.mark.asyncio
async def test_create_repository_template_repo_generate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    async def fake_github_request(method: str, path: str, **kwargs):
        calls.append((method, path, kwargs.get("json_body"), kwargs.get("headers")))
        if method == "GET" and path == "/user":
            return {"json": {"login": "me"}}
        if method == "POST" and path == "/repos/tpl/base/generate":
            body = kwargs.get("json_body") or {}
            assert body["owner"] == "acme"
            assert body["name"] == "demo"
            assert body["include_all_branches"] is False
            return {"status_code": 201, "json": {"full_name": "acme/demo"}}
        raise AssertionError(f"unexpected call: {method} {path}")

    monkeypatch.setattr(main, "_github_request", fake_github_request)
    monkeypatch.setattr(main, "_ensure_write_allowed", lambda *_a, **_k: None)

    result = await main.create_repository(
        name="demo",
        owner="acme",
        owner_type="org",
        template_full_name="tpl/base",
        description="from template",
    )

    assert result["full_name"] == "acme/demo"
    assert calls[1][:2] == ("POST", "/repos/tpl/base/generate")


@pytest.mark.asyncio
async def test_create_repository_overrides_update_and_topics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    async def fake_github_request(method: str, path: str, **kwargs):
        calls.append((method, path, kwargs.get("json_body"), kwargs.get("headers")))
        if method == "GET" and path == "/user":
            return {"json": {"login": "me"}}
        if method == "POST" and path == "/user/repos":
            body = kwargs.get("json_body") or {}
            assert body["has_downloads"] is False
            return {"status_code": 201, "json": {"full_name": "me/demo"}}
        if method == "PATCH" and path == "/repos/me/demo":
            body = kwargs.get("json_body") or {}
            assert body["allow_auto_merge"] is True
            return {"status_code": 200, "json": {"ok": True}}
        if method == "PUT" and path == "/repos/me/demo/topics":
            assert kwargs.get("headers") == {"Accept": "application/vnd.github+json"}
            body = kwargs.get("json_body") or {}
            assert body["names"] == ["one", "two"]
            return {"status_code": 200, "json": {"names": body["names"]}}
        raise AssertionError(f"unexpected call: {method} {path}")

    monkeypatch.setattr(main, "_github_request", fake_github_request)
    monkeypatch.setattr(main, "_ensure_write_allowed", lambda *_a, **_k: None)

    result = await main.create_repository(
        name="demo",
        create_payload_overrides={"has_downloads": False},
        update_payload_overrides={"allow_auto_merge": True},
        topics=["one", "two"],
    )

    assert result["full_name"] == "me/demo"
    assert ("PATCH", "/repos/me/demo") in [(c[0], c[1]) for c in calls]
    assert ("PUT", "/repos/me/demo/topics") in [(c[0], c[1]) for c in calls]


@pytest.mark.asyncio
async def test_create_repository_conflicting_visibility_returns_structured_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(main, "_ensure_write_allowed", lambda *_a, **_k: None)

    async def fake_github_request(method: str, path: str, **kwargs):
        raise AssertionError("should not call github request")

    monkeypatch.setattr(main, "_github_request", fake_github_request)

    result = await main.create_repository(name="demo", visibility="public", private=True)

    err = result.get("error") or {}
    assert err.get("error") == "ValueError"
    assert "visibility and private disagree" in (err.get("message") or "")
