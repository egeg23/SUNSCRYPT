import os

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_meta_is_public_and_safe(client):
    r = await client.get("/api/meta")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "SUNSCRYPT"
    assert body["registration"] in ("invite", "open")
    assert body["live_trading_enabled"] is False  # real money is off by default


async def test_health_reports_dependencies(client):
    r = await client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert set(body) >= {"status", "db", "redis", "version"}
    if os.environ.get("SUNS_REQUIRE_SERVICES") == "1":  # set in CI / compose where Postgres+Redis run
        assert body["status"] == "ok", body
