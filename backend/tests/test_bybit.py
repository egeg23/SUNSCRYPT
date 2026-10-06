import asyncio

import pytest

from app import bybit
from tests import bybit_fake


@pytest.fixture(autouse=True)
def fake_bybit(monkeypatch):
    monkeypatch.setattr(bybit, "transport", bybit_fake.transport)


def check(key: str, mode="demo"):
    return asyncio.run(bybit.check_key(mode, key, "secret-secret"))


def test_good_demo_key_accepted():
    chk = check("GOOD1234567890")
    assert chk.ok and chk.uta and not chk.problems


def test_withdraw_key_rejected():
    chk = check("WITHDRAW123456")
    assert not chk.ok
    assert any("переводы и вывод" in p for p in chk.problems)


def test_key_without_ip_rejected():
    chk = check("NOIP1234567890")
    assert not chk.ok and any("IP" in p for p in chk.problems)


def test_read_only_rejected():
    assert not check("READONLY123456").ok


def test_extra_permissions_warn_but_pass():
    chk = check("EXTRA123456789")
    assert chk.ok and any("спот" in w for w in chk.warnings)


def test_real_key_on_demo_explained():
    with pytest.raises(bybit.BybitError, match="реального счёта"):
        check("REAL1234567890")


def test_unknown_key():
    with pytest.raises(bybit.BybitError, match="не узнал ключ"):
        check("NOPE1234567890")


def test_evaluate_requires_server_ip_and_uta():
    chk = bybit.evaluate(
        {"permissions": {"ContractTrade": ["Order", "Position"]}, "ips": ["1.2.3.4"], "uta": 0},
        "109.73.198.185",
    )
    assert not chk.ok
    assert any("109.73.198.185" in p for p in chk.problems)
    assert any("UTA" in p for p in chk.problems)
