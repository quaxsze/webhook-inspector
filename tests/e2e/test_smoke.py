import os

import httpx
import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("E2E_BASE_URL"),
    reason="E2E_BASE_URL not set — start docker-compose and export E2E_BASE_URL=http://localhost",
)


@pytest.fixture
def base_app_url() -> str:
    return os.environ["E2E_BASE_URL"] + ":8000"


@pytest.fixture
def base_hook_url() -> str:
    return os.environ["E2E_BASE_URL"] + ":8001"


async def test_smoke_full_flow(base_app_url: str, base_hook_url: str) -> None:
    async with httpx.AsyncClient(timeout=10) as c:
        resp = await c.post(f"{base_app_url}/api/endpoints")
        assert resp.status_code == 201
        token = resp.json()["token"]

        for i in range(3):
            r = await c.post(f"{base_hook_url}/h/{token}", json={"i": i})
            assert r.status_code == 200

        listing = await c.get(f"{base_app_url}/api/endpoints/{token}/requests")
        assert listing.status_code == 200
        assert len(listing.json()["items"]) == 3
