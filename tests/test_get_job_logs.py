import io
import zipfile

import httpx
import pytest

from main import _decode_zipped_job_logs, get_job_logs


def test_decode_zipped_job_logs_combines_entries():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zip_file:
        zip_file.writestr("b.txt", "second line")
        zip_file.writestr("a.txt", "first line")

    result = _decode_zipped_job_logs(buffer.getvalue())

    assert result == "[a.txt]\nfirst line\n\n[b.txt]\nsecond line"


def test_decode_zipped_job_logs_handles_invalid_zip():
    assert _decode_zipped_job_logs(b"not-a-zip") == ""


@pytest.mark.asyncio
async def test_get_job_logs_follows_redirects(monkeypatch):
    class DummyClient:
        def build_request(self, method, url, headers=None):
            self.method = method
            self.url = url
            # httpx applies the client's default headers when building a request.
            self.headers = headers or {"Accept": "application/vnd.github+json"}
            return httpx.Request(method, url)

        async def send(self, request, follow_redirects=False):
            self.follow_redirects = follow_redirects
            return httpx.Response(
                200,
                content=b"hello world",
                headers={"Content-Type": "text/plain"},
                request=request,
            )

    dummy = DummyClient()

    from main import _http_client_github

    monkeypatch.setattr("main._http_client_github", dummy, raising=False)

    result = await get_job_logs("octo/demo", 123)

    assert dummy.follow_redirects is True
    assert dummy.headers.get("Accept") == "application/vnd.github+json"
    assert result["logs"] == "hello world"


@pytest.mark.asyncio
async def test_get_job_logs_respects_custom_truncation(monkeypatch):
    class DummyClient:
        def build_request(self, method, url, headers=None):
            return httpx.Request(method, url)

        async def send(self, request, follow_redirects=False):
            return httpx.Response(
                200,
                content=b"abcdef",
                headers={"Content-Type": "text/plain"},
                request=request,
            )

    dummy = DummyClient()

    from main import _http_client_github

    monkeypatch.setattr("main._http_client_github", dummy, raising=False)

    result = await get_job_logs("octo/demo", 123, logs_max_chars=3)

    assert result["logs"] == "abc"


@pytest.mark.asyncio
async def test_get_job_logs_can_disable_truncation(monkeypatch):
    long_payload = "log" * 100

    class DummyClient:
        def build_request(self, method, url, headers=None):
            return httpx.Request(method, url)

        async def send(self, request, follow_redirects=False):
            return httpx.Response(
                200,
                content=long_payload.encode(),
                headers={"Content-Type": "text/plain"},
                request=request,
            )

    dummy = DummyClient()

    from main import _http_client_github

    monkeypatch.setattr("main._http_client_github", dummy, raising=False)

    result = await get_job_logs("octo/demo", 123, logs_max_chars=0)

    assert result["logs"] == long_payload
