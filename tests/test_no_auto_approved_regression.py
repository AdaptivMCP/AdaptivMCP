import pytest

from github_mcp.main_tools.server_config import get_server_config
from github_mcp.http_routes.actions_compat import serialize_actions_for_compatibility

import github_mcp.server as server


def _contains_key(obj, key: str) -> bool:
    if isinstance(obj, dict):
        if key in obj:
            return True
        return any(_contains_key(v, key) for v in obj.values())
    if isinstance(obj, list):
        return any(_contains_key(v, key) for v in obj)
    return False


@pytest.mark.asyncio
async def test_server_config_does_not_advertise_auto_approved():
    cfg = await get_server_config()
    assert not _contains_key(cfg, "auto_approved")


def test_actions_compat_does_not_emit_auto_approved():
    actions = serialize_actions_for_compatibility(server)
    assert not _contains_key(actions, "auto_approved")
