from app import main
from tests.conftest import live


def test_status_defaults_to_demo_with_real_locked(client, flags):
    body = client.get("/api/status").json()
    assert body["default_mode"] == "demo"
    assert body["real_trading_allowed"] is False
    assert body["max_leverage"] == 2
    assert body["default_leverage"] == 1


def test_status_global_stop_blocks_real(client, flags):
    flags.update(real_trading_enabled=True, global_stop=True)
    body = client.get("/api/status").json()
    assert body["real_trading_allowed"] is False
    assert body["global_stop"] is True


def test_health_degraded_is_503(client, monkeypatch):
    async def down() -> bool:
        return False

    monkeypatch.setattr(main, "db_alive", down)
    monkeypatch.setattr(main, "redis_alive", down)
    r = client.get("/api/health")
    assert r.status_code == 503
    assert r.json()["status"] == "degraded"


@live
def test_health_live(client):
    r = client.get("/api/health")
    assert r.status_code == 200, r.text
    assert r.json() == {**r.json(), "status": "ok", "db": True, "redis": True}


@live
def test_status_live_reads_migrated_flags(client):
    body = client.get("/api/status").json()
    assert body["real_trading_allowed"] is False
    assert body["global_stop"] is False
