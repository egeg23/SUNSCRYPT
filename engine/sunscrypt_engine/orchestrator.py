"""Диспетчер движка (бриф, этап 4).

Каждые 10 секунд сверяет желаемое (кабинеты в базе) с действительным
(процессы-исполнители):
- кабинет с включённой торговлей, исправным ключом и без остановки →
  исполнитель должен работать; упал — перезапуск с нарастающей паузой;
  молчит дольше 2 минут — перезапуск;
- торговля выключена или кабинет остановлен → флаг остановки в Redis
  (исполнитель закрывает позиции), затем процесс гасится;
- общая аварийная остановка из базы → флаг для всех.
Реальный счёт — только при включённой владельцем реальной торговле.

Ещё: исполнения из Redis → журнал сделок; раз в минуту — снимок баланса;
раз в час — сверка журнала с Bybit (/v5/execution/list) с дописыванием
недостающих сделок.

Использует модели и шифрование бэкенда (backend/app), ключи расшифровывает
только чтобы передать процессу-исполнителю в окружении.

Запуск: python -m sunscrypt_engine.orchestrator
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app import bybit, safety
from app.accounts import active_secrets, keys_map, secrets_of
from app.cache import redis
from app.db import SessionLocal, read_flags
from app.models import EngineEvent, EquitySnapshot, ExchangeAccount, Funding, Trade
from sunscrypt_engine import keys

log = logging.getLogger("orchestrator")

PAIRS = os.environ.get("SIGNAL_PAIRS", "BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT,BNBUSDT,ADAUSDT")
LOOP_SECS = 10
HB_STALE_SECS = 120
STOP_GRACE_SECS = 180
DEFAULT_CAPITAL = 1000.0
# Модуль исполнителя; в тестах подменяется заглушкой.
EXECUTOR = os.environ.get("SUNS_EXECUTOR_MODULE", "sunscrypt_engine.executor")


@dataclass
class Proc:
    p: asyncio.subprocess.Process | None = None
    started: float = 0.0
    fails: int = 0
    next_try: float = 0.0
    stopping_since: float | None = None
    fingerprint: str = ""
    mode: str = ""  # счёт, на котором работает процесс
    log_task: asyncio.Task | None = field(default=None, repr=False)


class Orchestrator:
    def __init__(self) -> None:
        self.procs: dict[str, Proc] = {}
        self.key_tails: dict[str, str] = {}  # ключ активного счёта сменился — перезапуск
        self.last_equity = 0.0
        self.last_recon = 0.0

    # ── журнал движка ───────────────────────────────────────────────────────
    async def event(self, account_id, kind: str, message: str) -> None:
        log.info("%s %s: %s", account_id or "-", kind, message)
        async with SessionLocal() as db:
            db.add(EngineEvent(account_id=account_id, kind=kind, message=message[:500]))
            await db.commit()

    # ── процессы ────────────────────────────────────────────────────────────
    def _fingerprint(self, a: ExchangeAccount, capital: float) -> str:
        return f"{a.mode}|{a.leverage}|{capital}|{a.daily_loss_pct}|{PAIRS}|{self.key_tails.get(str(a.id))}"

    async def _capital(self, a: ExchangeAccount) -> float:
        if a.capital_usd:
            return a.capital_usd
        eq = a.equity_usd or DEFAULT_CAPITAL
        return min(eq, DEFAULT_CAPITAL)

    async def start(self, a: ExchangeAccount, real_ok: bool) -> None:
        aid = str(a.id)
        pr = self.procs.setdefault(aid, Proc())
        if time.time() < pr.next_try:
            return
        async with SessionLocal() as db:
            key, secret = await active_secrets(db, a)
        capital = await self._capital(a)
        await self._set_leverage(a, key, secret)
        env = {
            **{k: v for k, v in os.environ.items() if not k.startswith(("MASTER_KEY", "DATABASE_URL"))},
            "SUNS_ACCOUNT_ID": aid,
            "SUNS_API_KEY": key,
            "SUNS_API_SECRET": secret,
            "SUNS_MODE": a.mode,
            "SUNS_PAIRS": PAIRS,
            "SUNS_CAPITAL_USD": str(capital),
            "SUNS_LEVERAGE": str(safety.check_leverage(a.leverage)),
            "SUNS_DAILY_LOSS_PCT": str(a.daily_loss_pct),
        }
        if a.mode == "real" and real_ok:
            env["SUNS_REAL_CONFIRMED"] = "yes"
        await redis.set(keys.STOP_ACCOUNT.format(id=aid), "0")
        pr.p = await asyncio.create_subprocess_exec(
            sys.executable, "-m", EXECUTOR,
            env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        pr.started, pr.stopping_since = time.time(), None
        pr.fingerprint = self._fingerprint(a, capital)
        pr.mode = a.mode
        pr.log_task = asyncio.create_task(self._pipe_log(aid, pr.p))
        await self.event(a.id, "start", f"Исполнитель запущен: {a.mode}, капитал {capital:.0f} USD, "
                                         f"плечо {a.leverage}×, пары {PAIRS}")

    async def _pipe_log(self, aid: str, p: asyncio.subprocess.Process) -> None:
        """Лог исполнителя — в лог диспетчера с меткой кабинета (без ключей:
        адаптер Nautilus их маскирует)."""
        assert p.stdout
        async for line in p.stdout:
            sys.stdout.write(f"[{aid[:8]}] {line.decode(errors='replace')}")

    async def kill(self, aid: str, reason: str) -> None:
        pr = self.procs.get(aid)
        if not pr or not pr.p or pr.p.returncode is not None:
            return
        pr.p.send_signal(signal.SIGINT)
        try:
            await asyncio.wait_for(pr.p.wait(), 60)
        except TimeoutError:
            pr.p.kill()
            await pr.p.wait()
        pr.p = None  # остановлен намеренно — не падение
        await self.event(aid, "exit", f"Исполнитель остановлен: {reason}")

    async def _set_leverage(self, a: ExchangeAccount, key: str, secret: str) -> None:
        """Плечо на бирже = плечо кабинета (≤ 2×). Ответ «не изменилось» — норма."""
        lev = str(safety.check_leverage(a.leverage))
        for sym in PAIRS.split(","):
            body = {"category": "linear", "symbol": sym, "buyLeverage": lev, "sellLeverage": lev}
            try:
                await bybit.post(a.mode, key, secret, "/v5/position/set-leverage", body)  # type: ignore[arg-type]
            except bybit.BybitError:
                log.warning("плечо %s не выставлено", sym)

    # ── главный цикл ────────────────────────────────────────────────────────
    async def tick(self) -> None:
        async with SessionLocal() as db:
            flags = await read_flags(db)
            accounts = list(await db.scalars(select(ExchangeAccount)))
        global_stop = flags.get("global_stop", False)
        real_ok = safety.real_mode_allowed(flags.get("real_trading_enabled", False), global_stop)
        await redis.set(keys.STOP_GLOBAL, "1" if global_stop else "0")
        seen = set()
        for a in accounts:
            seen.add(str(a.id))
            try:
                await self._sync(a, global_stop, real_ok)
            except Exception as e:  # один сломанный кабинет не держит остальные
                log.exception("кабинет %s", a.id)
                await self.event(a.id, "error", f"Сбой диспетчера: {type(e).__name__}")
        for aid in list(self.procs):
            if aid not in seen:  # кабинет удалён
                await redis.set(keys.STOP_ACCOUNT.format(id=aid), "1")
                await self.kill(aid, "кабинет удалён")
                self.procs.pop(aid)

    async def _sync(self, a: ExchangeAccount, global_stop: bool, real_ok: bool) -> None:
        aid = str(a.id)
        want = (
            a.trading_enabled and a.status == "ok" and not a.stopped and not global_stop
            and (a.mode == "demo" or real_ok)
        )
        async with SessionLocal() as db:
            k = (await keys_map(db, a.id)).get(a.mode)
        self.key_tails[aid] = k.key_tail if k else ""
        pr = self.procs.get(aid)
        alive = pr is not None and pr.p is not None and pr.p.returncode is None
        if not want:
            if alive:
                await self._wind_down(a, pr)
            return
        if alive and pr.mode != a.mode:
            # Смена демо ↔ реальный: позиции на прежнем счёте закрываются, и
            # только после этого исполнитель запускается на новом — двойных
            # позиций нет (бриф, этап 5).
            await self._wind_down(a, pr, f"смена счёта: {pr.mode} → {a.mode}")
            return
        if alive and pr.fingerprint != self._fingerprint(a, await self._capital(a)):
            await self.kill(aid, "изменились настройки — перезапуск")
            alive = False
        if alive:
            await self._health(a, pr)
        else:
            if pr and pr.p and pr.p.returncode not in (None, 0):
                pr.fails += 1
                pr.next_try = time.time() + min(300, 10 * 2 ** min(pr.fails, 5))
                await self.event(a.id, "crash", f"Исполнитель упал (код {pr.p.returncode}); "
                                                f"повтор через {pr.next_try - time.time():.0f} с")
                pr.p = None
                return
            await self.start(a, real_ok)

    async def _wind_down(self, a: ExchangeAccount, pr: Proc, why: str | None = None) -> None:
        """Сначала исполнитель закрывает позиции по флагу, потом процесс гасится."""
        aid = str(a.id)
        await redis.set(keys.STOP_ACCOUNT.format(id=aid), "1")
        if pr.stopping_since is None:
            pr.stopping_since = time.time()
        raw = await redis.get(keys.HB_ACCOUNT.format(id=aid))
        hb = json.loads(raw) if raw else {}
        flat = hb.get("halted") and not hb.get("positions") and not hb.get("open_orders")
        if flat or time.time() - pr.stopping_since > STOP_GRACE_SECS:
            reason = why or ("остановлен" if a.stopped else "торговля выключена")
            await self.kill(aid, reason if flat else f"{reason}; позиции не подтвердили закрытие за 3 мин")

    async def _health(self, a: ExchangeAccount, pr: Proc) -> None:
        aid = str(a.id)
        raw = await redis.get(keys.HB_ACCOUNT.format(id=aid))
        age = time.time() - json.loads(raw)["ts"] / 1000 if raw else None
        if time.time() - pr.started > HB_STALE_SECS + 60 and (age is None or age > HB_STALE_SECS):
            await self.kill(aid, "нет сердцебиения больше 2 минут — перезапуск")
        elif age is not None and age < 60:
            pr.fails = 0

    # ── журнал сделок, баланс, сверка ───────────────────────────────────────
    async def drain_fills(self) -> None:
        for aid in list(self.procs):
            stream = keys.FILLS.format(id=aid)
            entries = await redis.xrange(stream, count=500)
            if not entries:
                continue
            rows = []
            for _id, f in entries:
                f = {k.decode(): v.decode() for k, v in f.items()}
                rows.append(dict(
                    account_id=aid, mode=f.get("mode", "demo"), trade_id=f["trade_id"], order_id=f.get("venue_order_id"),
                    sym=f["sym"], side=f["side"], qty=float(f["qty"]), price=float(f["price"]),
                    fee=float(f["fee"] or 0), fee_ccy=f.get("fee_ccy"), liquidity=f.get("liquidity"),
                    source="engine", ts=datetime.fromtimestamp(int(f["ts"]) / 1000, UTC),
                ))
            async with SessionLocal() as db:
                await db.execute(insert(Trade).values(rows).on_conflict_do_nothing())
                await db.commit()
            await redis.xdel(stream, *[e[0] for e in entries])
            # Снимок баланса на каждую сделку (бриф, этап 6).
            await self.snapshot_equity(only=aid, exact=True)

    async def snapshot_equity(self, only: str | None = None, exact: bool = False) -> None:
        async with SessionLocal() as db:
            q = select(ExchangeAccount).where(ExchangeAccount.trading_enabled)
            if only:
                q = q.where(ExchangeAccount.id == only)
            accounts = list(await db.scalars(q))
            now = datetime.now(UTC)
            if not exact:
                now = now.replace(second=0, microsecond=0)
            for a in accounts:
                try:
                    key, secret = await active_secrets(db, a)
                    eq = await bybit.equity(a.mode, key, secret)  # type: ignore[arg-type]
                except (bybit.BybitError, ValueError):
                    continue
                if eq is not None:
                    a.equity_usd = eq
                    await db.execute(insert(EquitySnapshot).values(
                        account_id=a.id, mode=a.mode, ts=now, equity_usd=eq).on_conflict_do_nothing())
            await db.commit()

    async def reconcile(self) -> None:
        """Журнал против Bybit за последние сутки: недостающие сделки дописываются."""
        since = datetime.now(UTC) - timedelta(hours=24)
        async with SessionLocal() as db:
            accounts = list(await db.scalars(select(ExchangeAccount).where(ExchangeAccount.trading_enabled)))
            for a in accounts:
                try:
                    key, secret = await active_secrets(db, a)
                except ValueError:
                    continue
                execs = await fetch_executions(a.mode, key, secret, since)
                if execs is None:
                    continue
                ours = set(await db.scalars(select(Trade.trade_id).where(
                    Trade.account_id == a.id, Trade.mode == a.mode, Trade.ts >= since)))
                for e in execs:
                    if e.get("execType") == "Funding":
                        await db.execute(insert(Funding).values(
                            account_id=a.id, mode=a.mode, exec_id=e["execId"], sym=e["symbol"],
                            amount=float(e.get("execFee") or 0),
                            ts=datetime.fromtimestamp(int(e["execTime"]) / 1000, UTC),
                        ).on_conflict_do_nothing())
                execs = [e for e in execs if e.get("execType") == "Trade"]
                missing = [e for e in execs if e["execId"] not in ours]
                theirs = {e["execId"] for e in execs}
                extra = [t for t in ours if t not in theirs]
                for e in missing:
                    await db.execute(insert(Trade).values(
                        account_id=a.id, mode=a.mode, trade_id=e["execId"], order_id=e.get("orderId"),
                        sym=e["symbol"], side=e["side"].lower(), qty=float(e["execQty"]),
                        price=float(e["execPrice"]), fee=float(e.get("execFee") or 0), fee_ccy="USDT",
                        liquidity="MAKER" if e.get("isMaker") else "TAKER", source="reconcile",
                        ts=datetime.fromtimestamp(int(e["execTime"]) / 1000, UTC),
                    ).on_conflict_do_nothing())
                await db.commit()
                res = {"ts": int(time.time() * 1000), "bybit": len(execs), "journal": len(ours),
                       "added": len(missing), "extra": len(extra)}
                await redis.set(f"recon:{a.id}", json.dumps(res), ex=3 * 3600)
                if missing or extra:
                    await self.event(a.id, "reconcile",
                                     f"Сверка с Bybit за сутки: у Bybit {len(execs)}, в журнале {len(ours)}; "
                                     f"дописано {len(missing)}, лишних в журнале {len(extra)}")

    async def run(self) -> None:
        await self.event(None, "orchestrator", "Диспетчер запущен")
        while True:
            try:
                await self.tick()
                await self.drain_fills()
                if time.time() - self.last_equity > 60:
                    self.last_equity = time.time()
                    await self.snapshot_equity()
                if time.time() - self.last_recon > 3600:
                    self.last_recon = time.time()
                    await self.reconcile()
            except Exception:
                log.exception("цикл диспетчера")
            await asyncio.sleep(LOOP_SECS)


async def fetch_executions(mode, key: str, secret: str, since: datetime) -> list[dict] | None:
    """Исполнения по линейным контрактам с момента since (постранично)."""
    out, cursor = [], ""
    start = str(int(since.timestamp() * 1000))
    for _ in range(20):
        q = f"category=linear&limit=100&startTime={start}" + (f"&cursor={cursor}" if cursor else "")
        try:
            data = await bybit._get(mode, key, secret, "/v5/execution/list", q)  # noqa: SLF001
        except bybit.BybitError:
            return None
        if data.get("retCode") != 0:
            return None
        res = data.get("result") or {}
        out += [e for e in res.get("list", []) if e.get("execType") in ("Trade", "Funding")]
        cursor = res.get("nextPageCursor") or ""
        if not cursor:
            break
    return out


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    asyncio.run(Orchestrator().run())


if __name__ == "__main__":
    main()
