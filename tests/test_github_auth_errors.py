import httpx
import pytest

import main


class _FakeClient:
    def __init__(self, status_code: int, message: str):
        self._status_code = status_code
        self._message = message

    async def request(self, *_, **__):
        return httpx.Response(
            status_code=self._status_code,
            json={"message": self._message},
            request=httpx.Request("GET", "https://api.github.com/search/code"),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [401, 403])
async def test_github_request_raises_auth_error(monkeypatch: pytest.MonkeyPatch, status_code: int):
    monkeypatch.setattr(main, "_github_client_instance", lambda: _FakeClient(status_code, "Requires authentication"))

    with pytest.raises(main.GitHubAuthError) as excinfo:
        await main._github_request("GET", "/search/code")

    message = str(excinfo.value)
    assert "authentication failed" in message.lower()
    assert str(status_code) in message
