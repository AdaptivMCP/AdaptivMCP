from __future__ import annotations


def test_tool_registry_uris_survive_forwarded_prefix_changes() -> None:
    """Simulate the reverse-proxy link-id changing mid-workflow.

    In production, the service may be mounted under an ephemeral prefix such as
    "/Adaptiv MCP/link_<id>". If that prefix changes (rekey / re-auth), clients
    must still be able to invoke tools without reconnecting.

    This test verifies two invariants:
    1) `resources[].uri` is stable across prefix changes (relative URI).
    2) Tool invocation via that relative URI continues to resolve to the
       underlying "/tools/{tool_name}" endpoint.
    """

    import main
    from starlette.testclient import TestClient

    client = TestClient(main.app)

    resp_a = client.get(
        "/tools",
        headers={"x-forwarded-prefix": "/Adaptiv MCP/link_old"},
    )
    assert resp_a.status_code == 200
    payload_a = resp_a.json()
    resources_a = list(payload_a.get("resources") or [])
    assert resources_a
    res_a = resources_a[0]

    resp_b = client.get(
        "/tools",
        headers={"x-forwarded-prefix": "/Adaptiv MCP/link_new"},
    )
    assert resp_b.status_code == 200
    payload_b = resp_b.json()
    resources_b = list(payload_b.get("resources") or [])
    assert resources_b
    res_b = resources_b[0]

    # `uri` should be stable and relative.
    assert res_a.get("uri") == res_b.get("uri")
    uri = str(res_a.get("uri") or "")
    assert uri.startswith("tools/")
    assert not uri.startswith("/")

    # `href` can vary with the forwarded prefix.
    href_a = str(res_a.get("href") or "")
    href_b = str(res_b.get("href") or "")
    assert href_a and href_b
    assert href_a != href_b
    assert href_a.startswith("/Adaptiv MCP/link_old/")
    assert href_b.startswith("/Adaptiv MCP/link_new/")

    # A client that cached the old catalog should still be able to invoke the
    # tool after the prefix changes by resolving the relative uri against the
    # new base URL.
    #
    # In the unit-test environment, we don't have an actual reverse proxy, so
    # we validate that the relative uri maps to the underlying tool detail
    # endpoint when rooted at "/".
    tool_detail_path = "/" + uri
    detail = client.get(tool_detail_path)
    assert detail.status_code == 200
    detail_payload = detail.json()
    assert detail_payload.get("name") == res_a.get("name")
