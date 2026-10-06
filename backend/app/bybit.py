"""Bybit v5: проверка API-ключа перед сохранением (бриф, этап 3).

Правила (бриф, раздел 3, правило 3):
- ключ с правом вывода или переводов (Wallet, Exchange) — отклоняем;
- нужен доступ к фьючерсам: ContractTrade — Order и Position;
- ключ только для чтения не подходит (торговать нечем);
- обязательна привязка к IP сервера (без «*»);
- счёт — единый торговый (UTA).
Лишние торговые права (спот, опционы) не мешают, но о них предупреждаем.

Ключ и секрет не логируются и не попадают в тексты ошибок.
"""

import hashlib
import hmac
import time
from dataclasses import dataclass, field
from typing import Literal

import httpx

from app.config import get_settings

Mode = Literal["demo", "real"]


def _host(mode: Mode) -> str:
    s = get_settings()
    return s.bybit_demo_url if mode == "demo" else s.bybit_real_url


# Права, которые дают вывести или перевести деньги.
FORBIDDEN = {"Wallet": "переводы и вывод", "Exchange": "обмен (Convert)"}
EXTRA_TRADE = {
    "Spot": "спот",
    "Options": "опционы",
    "Derivatives": "деривативы (классический счёт)",
    "CopyTrading": "копитрейдинг",
    "BlockTrade": "блочные сделки",
    "Earn": "Earn",
    "NFT": "NFT",
    "Affiliate": "партнёрка",
}

ERRORS = {
    10003: "Bybit не узнал ключ. Проверьте, что ключ скопирован целиком и что он для "
    "выбранного счёта (демо-ключи создаются в режиме Demo Trading).",
    10004: "Bybit не принял подпись: секрет ключа скопирован с ошибкой.",
    10010: "Ключ привязан к другому IP. Привяжите его к IP сервера {ip}.",
    33004: "Срок действия ключа истёк — создайте новый.",
}

# Для тестов: подменяется на httpx.MockTransport.
transport: httpx.AsyncBaseTransport | None = None


class BybitError(Exception):
    """Ошибка проверки, понятная человеку."""


@dataclass
class KeyCheck:
    ok: bool
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    permissions: dict[str, list[str]] = field(default_factory=dict)
    ips: list[str] = field(default_factory=list)
    uta: bool = False
    read_only: bool = False


async def _get(mode: Mode, key: str, secret: str, path: str, query: str = "") -> dict:
    ts, rw = str(int(time.time() * 1000)), "5000"
    sign = hmac.new(secret.encode(), (ts + key + rw + query).encode(), hashlib.sha256).hexdigest()
    headers = {
        "X-BAPI-API-KEY": key,
        "X-BAPI-TIMESTAMP": ts,
        "X-BAPI-RECV-WINDOW": rw,
        "X-BAPI-SIGN": sign,
    }
    url = _host(mode) + path + (f"?{query}" if query else "")
    try:
        async with httpx.AsyncClient(timeout=15, transport=transport) as client:
            r = await client.get(url, headers=headers)
    except httpx.HTTPError as e:
        raise BybitError("Bybit не ответил. Попробуйте ещё раз через минуту.") from e
    if r.status_code == 403:
        raise BybitError("Bybit закрыл доступ с этого адреса (403).")
    try:
        return r.json()
    except ValueError as e:
        raise BybitError(f"Bybit ответил непонятно (HTTP {r.status_code}).") from e


async def post(mode: Mode, key: str, secret: str, path: str, body: dict) -> dict:
    """Подписанный POST (например, установка плеча)."""
    import json

    raw = json.dumps(body, separators=(",", ":"))
    ts, rw = str(int(time.time() * 1000)), "5000"
    sign = hmac.new(secret.encode(), (ts + key + rw + raw).encode(), hashlib.sha256).hexdigest()
    headers = {
        "X-BAPI-API-KEY": key,
        "X-BAPI-TIMESTAMP": ts,
        "X-BAPI-RECV-WINDOW": rw,
        "X-BAPI-SIGN": sign,
        "content-type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=15, transport=transport) as client:
            r = await client.post(_host(mode) + path, content=raw, headers=headers)
        return r.json()
    except (httpx.HTTPError, ValueError) as e:
        raise BybitError("Bybit не ответил.") from e


def evaluate(result: dict, server_ip: str) -> KeyCheck:
    """Сверка прав ключа с правилами. Чистая функция — легко тестировать."""
    perms = {k: list(v) for k, v in (result.get("permissions") or {}).items() if v}
    ips = list(result.get("ips") or [])
    chk = KeyCheck(
        ok=False,
        permissions=perms,
        ips=ips,
        uta=bool(result.get("uta")) or result.get("unified") == 1,
        read_only=result.get("readOnly") == 1,
    )
    for name, title in FORBIDDEN.items():
        if perms.get(name):
            chk.problems.append(
                f"У ключа есть право «{title}» ({', '.join(perms[name])}). Такие ключи мы не "
                "принимаем: снимите эту галочку или создайте новый ключ."
            )
    if any("withdraw" in p.lower() for v in perms.values() for p in v):
        chk.problems.append("У ключа есть право вывода средств — такой ключ не принимаем.")
    contract = set(perms.get("ContractTrade", []))
    if not {"Order", "Position"} <= contract:
        chk.problems.append(
            "Нет нужных прав: включите Contracts (Unified Trading) → Orders и Positions."
        )
    if chk.read_only:
        chk.problems.append("Ключ только для чтения — выберите «Read-Write».")
    if not ips or "*" in ips:
        chk.problems.append(f"Ключ не привязан к IP. Привяжите его к IP сервера {server_ip}.")
    elif server_ip not in ips:
        chk.problems.append(
            f"Ключ привязан к другим IP ({', '.join(ips)}). Добавьте IP сервера {server_ip}."
        )
    if not chk.uta:
        chk.problems.append(
            "Счёт не единый торговый (UTA). Переведите счёт на Unified Trading в настройках Bybit."
        )
    extra = [EXTRA_TRADE[k] for k in perms if k in EXTRA_TRADE]
    if extra:
        chk.warnings.append(
            "Лишние права: " + ", ".join(extra) + ". Сервис ими не пользуется; безопаснее снять."
        )
    chk.ok = not chk.problems
    return chk


async def check_key(mode: Mode, key: str, secret: str) -> KeyCheck:
    """Спрашивает у Bybit сведения о ключе (только чтение) и сверяет с правилами."""
    ip = get_settings().server_ip
    data = await _get(mode, key, secret, "/v5/user/query-api")
    code = data.get("retCode")
    if code != 0:
        if mode == "demo" and code == 10003:
            other = await _get("real", key, secret, "/v5/user/query-api")
            if other.get("retCode") == 0:
                raise BybitError(
                    "Это ключ реального счёта, а выбран демо. Для демо создайте ключ в режиме "
                    "Demo Trading (аватар → Demo Trading → API)."
                )
        msg = ERRORS.get(code, "Bybit отклонил ключ (код {code}).")
        raise BybitError(msg.format(ip=ip, code=code))
    return evaluate(data.get("result") or {}, ip)


async def equity(mode: Mode, key: str, secret: str) -> float | None:
    """Баланс единого счёта в USD или None."""
    data = await _get(mode, key, secret, "/v5/account/wallet-balance", "accountType=UNIFIED")
    rows = (data.get("result") or {}).get("list") or []
    if data.get("retCode") != 0 or not rows:
        return None
    try:
        return float(rows[0].get("totalEquity") or 0)
    except (TypeError, ValueError):
        return None
