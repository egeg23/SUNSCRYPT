"""Стратегия исполнителя кабинета (бриф, этап 4): следует решениям сервиса
сигналов из Redis, а не считает модель сама.

Каждые 15 секунд:
1. Аварийная остановка (общая или кабинета) → отменить ордера, закрыть
   позиции, встать. Дневной лимит убытка → то же до конца суток UTC.
2. Для каждой пары: цель = target последнего свежего сигнала × объём на пару.
   Позиция приводится к цели. Мейкер: post-only лимитка по лучшей цене своей
   стороны, переставляется раз в минуту; не исполнилась за 20 минут — остаток
   рыночным ордером. Мелкие подстройки (< 25 % позиции) не делаются.
3. Сердцебиение в Redis: позиции, PnL, состояние.

Объём на пару = капитал × плечо / число пар; плечо ≤ 2 (бриф, правило 4).
Перезапуск безопасен: цель пересчитывается из сигнала, а не из памяти.
"""

from __future__ import annotations

import json
import time
from decimal import Decimal

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model import InstrumentId, OrderSide, TimeInForce
from nautilus_trader.trading import Strategy

from sunscrypt_engine import keys

MAX_LEVERAGE = 2.0
TICK_SECS = 15
REQUOTE_SECS = 60
MAKER_PATIENCE_SECS = 20 * 60


class FollowerConfig(StrategyConfig):
    def __init__(
        self,
        *,
        account_id: str,
        instrument_ids: list[InstrumentId],
        redis,
        capital_usd: float,
        leverage: float = 1.0,
        daily_loss_pct: float = 5.0,
        execution: str = "maker",
        mode: str = "demo",
        **_kw: object,
    ) -> None:
        super().__init__()
        if not 0 < leverage <= MAX_LEVERAGE:
            raise ValueError(f"плечо {leverage} вне (0, {MAX_LEVERAGE}]")
        self.account_id = account_id
        self.instrument_ids = instrument_ids
        self.redis = redis
        self.capital_usd = capital_usd
        self.leverage = leverage
        self.daily_loss_usd = capital_usd * daily_loss_pct / 100
        self.execution = execution
        self.mode = mode


def sym_of(iid) -> str:
    return str(iid).split("-")[0]


class FollowerStrategy(Strategy):
    def __init__(self, config: FollowerConfig) -> None:
        super().__init__(config)
        self.cfg = config
        self.r = config.redis
        self.halted: str | None = None
        self.loss_day: str | None = None
        self.order_born: dict[str, float] = {}  # client_order_id → время постановки
        self.target_since: dict[str, tuple[int, float]] = {}  # sym → (target, с какого момента)

    # ── жизненный цикл ──────────────────────────────────────────────────────
    def on_start(self) -> None:
        for iid in self.cfg.instrument_ids:
            self.subscribe_quotes(iid)
        self.clock.set_timer("tick", _secs(TICK_SECS), callback=self._tick)

    def on_stop(self) -> None:
        # Остановка процесса (выкатка, перезапуск) позиции не закрывает:
        # закрывает только явная аварийная остановка — см. _halt.
        for iid in self.cfg.instrument_ids:
            self.cancel_all_orders(iid)

    def on_order_filled(self, ev) -> None:
        fill = {
            "trade_id": str(ev.trade_id),
            "order_id": str(ev.client_order_id),
            "venue_order_id": str(ev.venue_order_id),
            "sym": sym_of(ev.instrument_id),
            "side": "buy" if ev.order_side == OrderSide.BUY else "sell",
            "qty": str(ev.last_qty),
            "price": str(ev.last_px),
            "fee": str(ev.commission.as_decimal()) if ev.commission else "0",
            "fee_ccy": str(ev.commission.currency) if ev.commission else "",
            "liquidity": str(ev.liquidity_side),
            "ts": str(ev.ts_event // 1_000_000),
            "mode": self.cfg.mode,
        }
        self.r.xadd(keys.FILLS.format(id=self.cfg.account_id), fill, maxlen=50000, approximate=True)

    # ── основной цикл ───────────────────────────────────────────────────────
    def _tick(self, _event=None) -> None:
        try:
            self._check_stops()
            if not self.halted:
                for iid in self.cfg.instrument_ids:
                    self._follow(iid)
        finally:
            self._heartbeat()

    def _pnl(self) -> float:
        total = 0.0
        for iid in self.cfg.instrument_ids:
            total += float(self.portfolio.realized_pnl(iid) or 0)
            total += float(self.portfolio.unrealized_pnl(iid) or 0)
        return total

    def _check_stops(self) -> None:
        aid = self.cfg.account_id
        day = time.strftime("%Y%m%d", time.gmtime(self._now()))
        reason = None
        if self.r.get(keys.STOP_GLOBAL) == b"1":
            reason = "общая аварийная остановка"
        elif self.r.get(keys.STOP_ACCOUNT.format(id=aid)) == b"1":
            reason = "кабинет остановлен"
        elif self.loss_day == day:
            reason = self.halted  # дневной лимит держится до конца суток UTC
        else:
            k = keys.DAY_PNL.format(id=aid, day=day)
            pnl, start = self._pnl(), self.r.get(k)
            if start is None:
                self.r.set(k, pnl, ex=3 * 86400)
                start = pnl
            if pnl - float(start) < -self.cfg.daily_loss_usd:
                reason = f"дневной лимит убытка ({pnl - float(start):.2f} USD)"
                self.loss_day = day
        if reason:
            self._halt(reason)
        else:
            self.halted = None

    def _halt(self, reason: str) -> None:
        if self.halted != reason:
            self.log.warning(f"остановка: {reason} — закрываю позиции")
        self.halted = reason
        for iid in self.cfg.instrument_ids:
            self.cancel_all_orders(iid)
            if float(self.portfolio.net_position(iid)) != 0:
                self.close_all_positions(iid)

    def _now(self) -> float:
        """Секунды по часам Nautilus: настоящие в живой торговле, симулированные в бэктесте."""
        return self.clock.timestamp_ns() / 1e9

    def _signal(self, sym: str) -> dict | None:
        raw = self.r.get(keys.SIGNAL.format(sym=sym))
        if not raw:
            return None
        sig = json.loads(raw)
        # Свежий — пока не подошло следующее решение (+1 свеча запаса).
        ttl_ms = (sig["horizon"] + 1) * sig["bar_minutes"] * 60_000
        return sig if self._now() * 1000 - sig["ts_close"] < ttl_ms else None

    def _mid(self, iid) -> float | None:
        q = self.cache.quote(iid)
        if q is None:
            return None
        return (float(q.bid_price) + float(q.ask_price)) / 2

    def _follow(self, iid) -> None:
        sym = sym_of(iid)
        sig = self._signal(sym)
        mid = self._mid(iid)
        inst = self.cache.instrument(iid)
        if sig is None or mid is None or inst is None:
            return  # нет сигнала — позицию не трогаем
        target = int(sig["target"])
        per_pair = self.cfg.capital_usd * self.cfg.leverage / len(self.cfg.instrument_ids)
        want = target * per_pair / mid
        cur = float(self.portfolio.net_position(iid))
        step = float(inst.size_increment)
        delta = round((want - cur) / step) * step
        prev = self.target_since.get(sym)
        if prev is None or prev[0] != target:
            self.target_since[sym] = (target, self._now())
        open_orders = self.cache.orders_open(instrument_id=iid)
        if abs(delta) < step / 2 or (
            cur and target and (cur > 0) == (target > 0) and abs(delta) < 0.25 * abs(cur)
        ):
            for o in open_orders:
                self.cancel_order(o)
            return
        now = self._now()
        if open_orders:
            stale = [o for o in open_orders if now - self.order_born.get(str(o.client_order_id), now) > REQUOTE_SECS]
            for o in stale:
                self.cancel_order(o)
            return
        side = OrderSide.BUY if delta > 0 else OrderSide.SELL
        qty = inst.make_qty(Decimal(str(abs(delta))))
        reduce_only = target == 0 or (cur != 0 and abs(want) < abs(cur) and (want > 0) == (cur > 0))
        waited = now - self.target_since[sym][1]
        if self.cfg.execution == "maker" and waited < MAKER_PATIENCE_SECS:
            q = self.cache.quote(iid)
            px = q.bid_price if side == OrderSide.BUY else q.ask_price
            order = self.order_factory.limit(
                iid, side, qty, px, post_only=True, reduce_only=reduce_only,
                time_in_force=TimeInForce.GTC,
            )
        else:
            order = self.order_factory.market(iid, side, qty, reduce_only=reduce_only)
        self.order_born[str(order.client_order_id)] = now
        self.submit_order(order)

    def _heartbeat(self) -> None:
        pos = {sym_of(i): float(self.portfolio.net_position(i)) for i in self.cfg.instrument_ids}
        hb = {
            "ts": int(self._now() * 1000),
            "positions": {k: v for k, v in pos.items() if v},
            "pnl": round(self._pnl(), 4),
            "halted": self.halted,
            "open_orders": len(self.cache.orders_open()),
        }
        self.r.set(keys.HB_ACCOUNT.format(id=self.cfg.account_id), json.dumps(hb), ex=120)


def _secs(s: int):
    import datetime as dt

    return dt.timedelta(seconds=s)
