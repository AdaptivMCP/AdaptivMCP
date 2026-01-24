from __future__ import annotations


def test_tool_catalog_uses_relative_uris_for_stability() -> None:
    """The tool catalog should not bake an ephemeral base path into `uri`.

    Some deployments mount the service under a per-link prefix (e.g.
    "/Adaptiv MCP/link_<id>"). If that link id changes during an interactive
    workflow, clients that cache the old absolute URIs can fail to reconnect.

    We mitigate this by exposing `uri` as a relative path ("tools/<name>")
    and providing an optional `href` for explicit HTTP invocation.
    """

    from github_mcp.http_routes import tool_registry

    # Exercise the pure function; do not require Starlette.
    catalog = tool_registry._tool_catalog(
        include_parameters=False,
        compact=True,
        base_path="/some/ephemeral/prefix",
    )

    resources = list(catalog.get("resources") or [])
    assert resources, "Expected at least one resource"
    for res in resources:
        uri = res.get("uri")
        assert isinstance(uri, str)
        assert uri.startswith("tools/")
        assert not uri.startswith("/")

        href = res.get("href")
        assert isinstance(href, str)
        assert "/tools/" in href
