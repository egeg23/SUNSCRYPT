import base64
import os

# До импорта приложения: тестовые настройки.
os.environ.setdefault("MASTER_KEY", base64.b64encode(os.urandom(32)).decode())
os.environ.setdefault("DB_NULLPOOL", "1")
os.environ.setdefault("PUBLIC_URL", "https://sunscrypt.test")
if os.environ.get("SUNSCRYPT_TEST_LIVE") == "1":
    os.environ.setdefault("OWNER_EMAIL", "owner@example.com")
    os.environ.setdefault("OWNER_PASSWORD", "owner long password")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app, get_flags  # noqa: E402

LIVE = os.environ.get("SUNSCRYPT_TEST_LIVE") == "1"

# Тесты с настоящими PostgreSQL и Redis — в CI (там подняты сервисы) или
# локально с SUNSCRYPT_TEST_LIVE=1.
live = pytest.mark.skipif(not LIVE, reason="нужны PostgreSQL и Redis")


@pytest.fixture(scope="session")
def _client():
    with TestClient(app, base_url="https://testserver") as c:
        yield c


@pytest.fixture
def client(_client):
    _client.cookies.clear()
    if LIVE:
        # Лимиты частоты копятся между тестами — начинаем с чистого Redis.
        import redis

        redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0")).flushdb()
    yield _client
    app.dependency_overrides.clear()


@pytest.fixture
def flags():
    """Подменяет флаги из базы: тест задаёт их сам."""
    values: dict[str, bool] = {}
    app.dependency_overrides[get_flags] = lambda: values
    return values
