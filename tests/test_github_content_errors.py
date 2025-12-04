import pytest

import main
from main import GitHubAPIError


@pytest.mark.asyncio
async def test_decode_github_content_surfaces_effective_ref(monkeypatch):
    def fake_effective_ref(full_name: str, ref: str | None) -> str:
        assert full_name == "owner/repo"
        assert ref is None
        return "issue-137"

    async def fake_github_request(*args, **kwargs):
        raise GitHubAPIError("GitHub API error 404 for GET /repos/owner/repo/contents/main.py")

    monkeypatch.setattr(main, "_effective_ref_for_repo", fake_effective_ref)
    monkeypatch.setattr(main, "_github_request", fake_github_request)

    with pytest.raises(GitHubAPIError) as excinfo:
        await main._decode_github_content("owner/repo", "main.py", None)

    message = str(excinfo.value)
    assert "issue-137" in message
    assert "owner/repo/main.py" in message


@pytest.mark.asyncio
async def test_fetch_files_uses_structured_error_envelope(monkeypatch):
    async def fake_decode(full_name: str, path: str, ref: str | None):
        if path == "ok.txt":
            return {"path": path, "content": "ok"}
        raise GitHubAPIError(f"boom reading {path}")

    monkeypatch.setattr(main, "_decode_github_content", fake_decode)

    result = await main.fetch_files("owner/repo", paths=["ok.txt", "bad.txt"], ref="main")

    assert set(result["files"].keys()) == {"ok.txt", "bad.txt"}
    assert result["files"]["ok.txt"]["content"] == "ok"

    error_entry = result["files"]["bad.txt"]
    assert isinstance(error_entry, dict)
    assert "error" in error_entry
    assert error_entry["error"]["context"] == "fetch_files"
    assert error_entry["error"]["path"] == "bad.txt"
    assert "boom reading bad.txt" in error_entry["error"]["message"]


@pytest.mark.asyncio
async def test_fetch_url_uses_structured_error_on_client_failure(monkeypatch):
    class DummyResponse:
        def __init__(self, status_code: int = 200, text: str = "ok", headers: dict | None = None):
            self.status_code = status_code
            self.text = text
            self.headers = headers or {}

    class DummyClient:
        def __init__(self, should_fail: bool = False):
            self.should_fail = should_fail

        async def get(self, url: str) -> DummyResponse:
            if self.should_fail:
                raise RuntimeError("network down")
            return DummyResponse(status_code=200, text="hello", headers={"X-Test": "1"})

    def fake_client_instance_fail():
        return DummyClient(should_fail=True)

    monkeypatch.setattr(main, "_external_client_instance", fake_client_instance_fail)

    error_result = await main.fetch_url("https://example.invalid/test")

    assert "error" in error_result
    envelope = error_result["error"]
    assert envelope["context"] == "fetch_url"
    assert envelope["path"] == "https://example.invalid/test"
    assert "network down" in envelope["message"]

    def fake_client_instance_ok():
        return DummyClient(should_fail=False)

    monkeypatch.setattr(main, "_external_client_instance", fake_client_instance_ok)

    ok_result = await main.fetch_url("https://example.com/")

    assert ok_result["status_code"] == 200
    assert ok_result["content"] == "hello"
    assert ok_result["headers"]["X-Test"] == "1"
