"""비동기 공공포털 경로와 EX 진단의 live E2E."""

import os

import pytest

from krex import KrexClient
from krex._env import get_local_env_value

pytestmark = pytest.mark.live


async def test_live_go_restarea_standard() -> None:
    if os.getenv("KEX_LIVE") != "1":
        pytest.skip("set KEX_LIVE=1")
    if not get_local_env_value("DATA_GO_KR_SERVICE_KEY"):
        pytest.skip("DATA_GO_KR_SERVICE_KEY is not set")
    async with KrexClient.from_env(timeout=20, max_retries=1) as client:
        page = await client.restarea.list_all(num_of_rows=1)
        assert page.raw is not None
        assert page.total_count is not None
        assert page.items
        assert isinstance(page.items[0].name, str)


async def test_live_ex_debug() -> None:
    if os.getenv("KEX_LIVE") != "1":
        pytest.skip("set KEX_LIVE=1")
    if not get_local_env_value("KEX_EX_API_KEY"):
        pytest.skip("KEX_EX_API_KEY is not set")
    async with KrexClient.from_env(timeout=20, max_retries=1) as client:
        run = await client.debug_call("restarea.route_facilities", num_of_rows=1)
        assert run.error is None, run.error
        assert run.response["status_code"] == 200
        assert run.parsed.items
