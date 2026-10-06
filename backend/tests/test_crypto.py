import base64
import os

import pytest
from cryptography.exceptions import InvalidTag

from app import crypto
from app.config import get_settings


def _set(monkeypatch, current: bytes, previous: bytes | None = None):
    monkeypatch.setenv("MASTER_KEY", base64.b64encode(current).decode())
    if previous:
        monkeypatch.setenv("MASTER_KEY_PREVIOUS", base64.b64encode(previous).decode())
    else:
        monkeypatch.delenv("MASTER_KEY_PREVIOUS", raising=False)
    get_settings.cache_clear()
    crypto._keys.cache_clear()


@pytest.fixture(autouse=True)
def restore(monkeypatch):
    yield
    get_settings.cache_clear()
    crypto._keys.cache_clear()


def test_roundtrip_and_purpose_binding(monkeypatch):
    _set(monkeypatch, os.urandom(32))
    blob = crypto.encrypt(b"secret", "a")
    assert crypto.decrypt(blob, "a") == b"secret"
    assert b"secret" not in blob
    with pytest.raises(InvalidTag):
        crypto.decrypt(blob, "b")


def test_master_key_rotation(monkeypatch):
    old, new = os.urandom(32), os.urandom(32)
    _set(monkeypatch, old)
    blob = crypto.encrypt(b"secret", "a")
    _set(monkeypatch, new, previous=old)
    assert not crypto.is_current(blob)
    assert crypto.decrypt(blob, "a") == b"secret"
    fresh = crypto.encrypt(crypto.decrypt(blob, "a"), "a")
    assert crypto.is_current(fresh)
    _set(monkeypatch, new)
    assert crypto.decrypt(fresh, "a") == b"secret"
    with pytest.raises(ValueError):
        crypto.decrypt(blob, "a")
