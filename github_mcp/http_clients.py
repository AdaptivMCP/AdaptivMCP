import time
from typing import Any, Dict, Optional

import httpx

from .config import GITHUB_API_BASE_URL, GITHUB_REQUEST_TIMEOUT_SECONDS
from .exceptions import GitHubAPIError, GitHubAuthError
from .tool_logging import _record_github_request


class _GitHubClientProtocol:
    """Structural protocol for httpx.Client-like objects used in this module.

    This keeps the dependency on httpx light while still allowing tests to
    provide simple fakes. We do not import typing.Protocol directly here to avoid
    additional overhead at import time.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:  # pragma: no cover - protocol only
        ...

    def get(self, url: str, **kwargs: Any) -> httpx.Response:  # pragma: no cover - protocol only
        ...

    def post(self, url: str, **kwargs: Any) -> httpx.Response:  # pragma: no cover - protocol only
        ...

    def close(self) -> None:  # pragma: no cover - protocol only
        ...


def _build_default_client() -> httpx.Client:
    """Return a default httpx.Client configured for GitHub's API.

    This helper centralizes shared configuration like timeouts and base URL so
    callers can focus on higher-level behavior.
    """

    return httpx.Client(base_url=GITHUB_API_BASE_URL, timeout=GITHUB_REQUEST_TIMEOUT_SECONDS)


def _request_with_metrics(
    method: str,
    url: str,
    *,
    client_factory: Optional[callable] = None,
    **kwargs: Any,
) -> httpx.Response:
    """Perform an HTTP request and record lightweight timing/response metadata.

    The HTTP client is constructed lazily so tests can inject a custom
    ``client_factory``. In the common case we reuse a simple default client.
    """

    start = time.time()
    client_factory = client_factory or _build_default_client

    try:
        client = client_factory()
    except GitHubAuthError:
        # Authentication failures are surfaced via structured exceptions so
        # callers can present clear error messages to users instead of generic
        # connection errors. We still record timing metadata for observability.
        _record_github_request(
            status_code=None, duration_ms=int((time.time() - start) * 1000), error=True
        )
        raise

    try:
        response = client.request(method, url, **kwargs)
    except httpx.HTTPError as exc:  # pragma: no cover - network failures are hard to force
        _record_github_request(
            status_code=None, duration_ms=int((time.time() - start) * 1000), error=True
        )
        raise GitHubAPIError(f"GitHub request failed: {exc}") from exc
    finally:
        client.close()

    _record_github_request(
        status_code=response.status_code,
        duration_ms=int((time.time() - start) * 1000),
        error=response.is_error,
    )

    if response.status_code == 401:
        raise GitHubAuthError("GitHub authentication failed. Check your token and permissions.")

    if response.is_error:
        raise GitHubAPIError(
            f"GitHub API error {response.status_code}: {response.text[:200]}"
        )

    return response
