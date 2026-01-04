import asyncio

from github_mcp import http_clients


def _run_in_loop(loop: asyncio.AbstractEventLoop, fn):
    async def _wrapper():
        return fn()

    return loop.run_until_complete(_wrapper())


def test_async_clients_refresh_when_event_loop_changes():
    # Start with a clean slate for global client state.
    http_clients._http_client_github = None
    http_clients._http_client_github_loop = None
    http_clients._http_client_external = None
    http_clients._http_client_external_loop = None

    loop1 = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop1)
        github_client1 = _run_in_loop(loop1, http_clients._github_client_instance)
        external_client1 = _run_in_loop(loop1, http_clients._external_client_instance)

        assert (
            _run_in_loop(loop1, http_clients._github_client_instance) is github_client1
        )
        assert (
            _run_in_loop(loop1, http_clients._external_client_instance)
            is external_client1
        )
    finally:
        loop1.run_until_complete(github_client1.aclose())
        loop1.run_until_complete(external_client1.aclose())
        loop1.close()

    loop2 = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop2)
        github_client2 = _run_in_loop(loop2, http_clients._github_client_instance)
        external_client2 = _run_in_loop(loop2, http_clients._external_client_instance)

        assert github_client2 is not github_client1
        assert external_client2 is not external_client1
        assert (
            _run_in_loop(loop2, http_clients._github_client_instance) is github_client2
        )
        assert (
            _run_in_loop(loop2, http_clients._external_client_instance)
            is external_client2
        )
    finally:
        loop2.run_until_complete(github_client2.aclose())
        loop2.run_until_complete(external_client2.aclose())
        loop2.close()

    asyncio.set_event_loop(None)
