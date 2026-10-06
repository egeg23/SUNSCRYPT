"""Поддельный Bybit для тестов: из облака настоящий закрыт гео-блоком.

Ключи: GOOD… — правильный демо-ключ; WITHDRAW… — с правом переводов/вывода;
NOIP… — без привязки к IP; READONLY… — только чтение; REAL… — ключ реального
счёта (на демо — 10003); остальное — неизвестный ключ."""

import httpx

SERVER_IP = "109.73.198.185"

BASE = {
    "readOnly": 0,
    "permissions": {
        "ContractTrade": ["Order", "Position"],
        "Spot": [],
        "Wallet": [],
        "Options": [],
        "Derivatives": [],
        "Exchange": [],
    },
    "ips": [SERVER_IP],
    "uta": 1,
}


def _info(key: str) -> dict:
    r = {**BASE, "permissions": dict(BASE["permissions"])}
    if key.startswith("WITHDRAW"):
        r["permissions"]["Wallet"] = ["AccountTransfer", "SubMemberTransfer", "Withdraw"]
    if key.startswith("NOIP"):
        r["ips"] = ["*"]
    if key.startswith("READONLY"):
        r["readOnly"] = 1
    if key.startswith("EXTRA"):
        r["permissions"]["Spot"] = ["SpotTrade"]
    return r


def handler(request: httpx.Request) -> httpx.Response:
    key = request.headers.get("X-BAPI-API-KEY", "")
    demo = request.url.host == "api-demo.bybit.com"
    known = key.startswith(("GOOD", "WITHDRAW", "NOIP", "READONLY", "EXTRA"))
    if key.startswith("REAL"):
        known = not demo
    if not known:
        return httpx.Response(200, json={"retCode": 10003, "retMsg": "API key is invalid."})
    if request.url.path == "/v5/user/query-api":
        return httpx.Response(200, json={"retCode": 0, "result": _info(key)})
    if request.url.path == "/v5/account/wallet-balance":
        return httpx.Response(
            200, json={"retCode": 0, "result": {"list": [{"totalEquity": "10000.5"}]}}
        )
    return httpx.Response(404)


transport = httpx.MockTransport(handler)
