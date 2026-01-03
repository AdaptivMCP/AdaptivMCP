from github_mcp.http_routes import healthz


def test_healthz_payload_excludes_metrics():
    payload = healthz._build_health_payload()
    assert "metrics" not in payload
