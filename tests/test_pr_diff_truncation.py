import httpx
import pytest

import main


@pytest.mark.asyncio
async def test_get_pr_diff_disables_truncation(monkeypatch):
    long_diff = "diff --git a/a.txt b/a.txt\n" + ("+line\n" * 1000)

    class DummyClient:
        async def request(self, method, path, params=None, json=None, headers=None):  # noqa: ARG002
            return httpx.Response(
                200,
                text=long_diff,
                headers={"Content-Type": "text/plain"},
                request=httpx.Request(method, path),
            )

    monkeypatch.setattr("main._http_client_github", DummyClient())

    result = await main.get_pr_diff("octo/demo", 1)

    assert result["status_code"] == 200
    assert result["text"].count("+line") == long_diff.count("+line")
