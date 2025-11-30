import httpx
import pytest
import main


def test_tool_metrics_simple():
    main._reset_metrics_for_tests()

    @main.mcp_tool(name='test_metric_tool', write_action=True)
    def tool():
        return 'ok'

    result = tool()
    assert result == 'ok'

    tools = main._METRICS['tools']['test_metric_tool']
    assert tools['calls_total'] == 1
    assert tools['errors_total'] == 0
    assert tools['write_calls_total'] == 1
    assert tools['latency_ms_sum'] >= 0


@pytest.mark.asyncio
async def test_github_metrics_success(monkeypatch):
    main._reset_metrics_for_tests()

    class DummyResponse:
        def __init__(self):
            self.status_code = 200
            self.headers = {
                'X-RateLimit-Limit': '5000',
                'X-RateLimit-Remaining': '10',
                'X-RateLimit-Reset': '123456',
            }
            self.text = 'ok'

        def json(self):
            return {'ok': True}

    class DummyClient:
        async def request(self, method, path, params=None, json=None, headers=None):
            return DummyResponse()

    client = DummyClient()
    monkeypatch.setattr(main, '_github_client_instance', lambda: client)

    result = await main._github_request('GET', '/dummy/path')

    assert result['status_code'] == 200
    github = main._METRICS['github']
    assert github['requests_total'] == 1
    assert github['errors_total'] == 0
    assert github['rate_limit_events_total'] == 0
    assert github['timeouts_total'] == 0
