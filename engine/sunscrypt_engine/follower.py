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

На каждую сделку — её результат (закрытая часть позиции против средней цены
входа, минус комиссия) и итог сделок за сутки UTC: для уведомлений.

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
# Столько отказов «мейкер-заявка исполнилась бы сразу» подряд — и дальше по
# рынку: на быстром рынке (и на демо) лимитка у края стакана может не
# встать никогда, а у моментума весь смысл — во входе в начале суток.
MAKER_REJECTS_MAX = 3
# Заявка больше стольких долей пары — значит, на счёте чужая позиция (ручная,
# другой бот): исполнитель её не трогает и зовёт человека. Свой переворот —
# до 2 долей (+ движение цены), поэтому 3. Так 06.10 исполнитель закрыл чужие
# 55.7 BTC (4.7 млн USD) на демо-счёте владельца.
MAX_ORDER_SHARES = 3.0


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
        max_drawdown_pct: float = 40.0,
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
        self.max_drawdown_usd = capital_usd * max_drawdown_pct / 100
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
        self.day: str | None = None
        self.day_start_pnl = 0.0
        self.carry = 0.0
        self.total_carry: float | None = None  # результат прежних процессов
        self.total_start = 0.0
        self.order_born: dict[str, float] = {}  # client_order_id → время постановки
        self.target_since: dict[str, tuple[int, float]] = {}  # sym → (target, с какого момента)
        self.maker_rejects: dict[str, int] = {}  # sym → отказы post-only подряд
        self.book: dict[str, tuple[float, float]] = {}  # sym → (позиция со знаком, средняя цена входа)
        self.blocked: dict[str, str] = {}  # sym → почему пара не трогается

    # ── жизненный цикл ──────────────────────────────────────────────────────
    def on_start(self) -> None:
        for iid in self.cfg.instrument_ids:
            self.subscribe_quotes(iid)
            # Позиции на бирже к старту уже сверены узлом — с них и считаем.
            q, avg = 0.0, 0.0
            for p in self.cache.positions_open(instrument_id=iid):
                q, avg = q + float(p.signed_qty), float(p.avg_px_open)
            self.book[sym_of(iid)] = (q, avg)
        self.clock.set_timer("tick", _secs(TICK_SECS), callback=self._tick)

    def on_stop(self) -> None:
        # Остановка процесса (выкатка, перезапуск) позиции не закрывает:
        # закрывает только явная аварийная остановка — см. _halt.
        for iid in self.cfg.instrument_ids:
            self.cancel_all_orders(iid)

    def on_order_rejected(self, ev) -> None:
        if getattr(ev, "due_post_only", False):
            sym = sym_of(ev.instrument_id)
            self.maker_rejects[sym] = self.maker_rejects.get(sym, 0) + 1

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
        # Сразу в браузер (дашборд, этап 6) и в Telegram: сделка, её
        # результат и итог дня.
        self.r.publish(
            keys.LIVE.format(id=self.cfg.account_id),
            json.dumps({"type": "fill", **fill, **self._fill_result_safe(fill)}),
        )
        self._heartbeat()

    def _fill_result_safe(self, fill: dict) -> dict:
        try:
            return self._fill_result(fill)
        except Exception as e:  # сделка в журнале важнее подсчёта для уведомления
            self.log.warning(f"результат сделки не посчитан: {e!r}")
            return {}

    def _fill_result(self, fill: dict) -> dict:
        sym, qty, px = fill["sym"], float(fill["qty"]), float(fill["price"])
        sign = 1.0 if fill["side"] == "buy" else -1.0
        q, avg = self.book.get(sym, (0.0, 0.0))
        q2, avg2, closed, gross = apply_fill(q, avg, sign, qty, px)
        self.book[sym] = (q2, avg2)
        fee = float(fill["fee"] or 0) if fill["fee_ccy"] in ("", "USDT") else 0.0
        net = gross - fee
        day = time.strftime("%Y%m%d", time.gmtime(int(fill["ts"]) / 1000))
        key = keys.DAY_NET.format(id=self.cfg.account_id, mode=self.cfg.mode, day=day)
        day_net = float(self.r.hincrbyfloat(key, "net", net))
        day_n = int(self.r.hincrby(key, "n", 1))
        self.r.expire(key, 3 * 86400)
        return {
            "pos_before": q,
            "pos_after": q2,
            "closed_qty": closed,
            "pnl": round(gross, 4),
            "net": round(net, 4),
            "entry_px": avg if closed else None,
            "day_net": round(day_net, 4),
            "day_fills": day_n,
        }

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
        pnl = self._pnl()
        if day != self.day:
            # Новые сутки или новый процесс: убыток за сутки складывается из
            # прежних процессов (Redis) и этого — перезапуск его не обнуляет.
            self.day, self.day_start_pnl = day, pnl
            self.carry = float(self.r.get(keys.DAY_TOTAL.format(id=aid, day=day)) or 0)
        day_total = self.carry + pnl - self.day_start_pnl
        self.r.set(keys.DAY_TOTAL.format(id=aid, day=day), day_total, ex=3 * 86400)
        halt_key = keys.DAY_HALT.format(id=aid, day=day)
        if day_total < -self.cfg.daily_loss_usd and not self.r.exists(halt_key):
            self.r.set(halt_key, f"дневной лимит убытка ({day_total:.2f} USD)", ex=2 * 86400)
        # Просадка от пика результата стратегии (не только за сутки: плохие
        # периоды у моментума — череда умеренно плохих дней). Держится до
        # решения человека (снятие остановки кабинета).
        mode = self.cfg.mode
        if self.total_carry is None:
            self.total_carry = float(self.r.get(keys.TOTAL.format(id=aid, mode=mode)) or 0)
            self.total_start = pnl
        total = self.total_carry + pnl - self.total_start
        peak = max(float(self.r.get(keys.PEAK.format(id=aid, mode=mode)) or 0), total)
        self.r.set(keys.TOTAL.format(id=aid, mode=mode), total)
        self.r.set(keys.PEAK.format(id=aid, mode=mode), peak)
        dd_key = keys.DD_HALT.format(id=aid, mode=mode)
        if peak - total > self.cfg.max_drawdown_usd and not self.r.exists(dd_key):
            self.r.set(dd_key, f"лимит просадки: −{peak - total:.2f} USD от пика (>{self.cfg.max_drawdown_usd:.0f})")
        reason = None
        if self.r.get(keys.STOP_GLOBAL) == b"1":
            reason = "общая аварийная остановка"
        elif self.r.get(keys.STOP_ACCOUNT.format(id=aid)) == b"1":
            reason = "кабинет остановлен"
        elif (h := self.r.get(dd_key)) is not None:
            reason = h.decode()
        elif (h := self.r.get(halt_key)) is not None:
            reason = h.decode()  # держится до конца суток UTC, и после перезапуска
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
        open_orders = self.cache.orders_open(instrument_id=iid)
        if abs(delta) * mid > MAX_ORDER_SHARES * per_pair:
            why = (
                f"позиция {cur:g} ({abs(cur) * mid:,.0f} USD) больше доли пары "
                f"({per_pair:,.0f} USD) — похоже, не наша; пара не трогается"
            ).replace(",", " ")
            if self.blocked.get(sym) != why:
                self.log.warning(f"{sym}: {why}")
            self.blocked[sym] = why
            for o in open_orders:
                self.cancel_order(o.client_order_id)
            return
        self.blocked.pop(sym, None)
        prev = self.target_since.get(sym)
        if prev is None or prev[0] != target:
            self.target_since[sym] = (target, self._now())
            self.maker_rejects[sym] = 0
        if abs(delta) < step / 2 or (
            cur and target and (cur > 0) == (target > 0) and abs(delta) < 0.25 * abs(cur)
        ):
            for o in open_orders:
                self.cancel_order(o.client_order_id)
            return
        now = self._now()
        if open_orders:
            # Ордер прошлого процесса (после перезапуска пришёл из сверки с
            # биржей): время постановки неизвестно — отсчёт с первой встречи.
            # Иначе он навсегда «свежий» и висит по старой цене.
            for o in open_orders:
                self.order_born.setdefault(str(o.client_order_id), now)
            stale = [o for o in open_orders if now - self.order_born[str(o.client_order_id)] > REQUOTE_SECS]
            for o in stale:
                self.cancel_order(o.client_order_id)
            return
        side = OrderSide.BUY if delta > 0 else OrderSide.SELL
        qty = inst.make_qty(Decimal(str(abs(delta))))
        reduce_only = target == 0 or (cur != 0 and abs(want) < abs(cur) and (want > 0) == (cur > 0))
        waited = now - self.target_since[sym][1]
        if (self.cfg.execution == "maker" and waited < MAKER_PATIENCE_SECS
                and self.maker_rejects.get(sym, 0) < MAKER_REJECTS_MAX):
            px = self._maker_price(iid, side)
            order = self.order_factory.limit(
                iid, side, qty, px, post_only=True, reduce_only=reduce_only,
                time_in_force=TimeInForce.GTC,
            )
        else:
            order = self.order_factory.market(iid, side, qty, reduce_only=reduce_only)
        self.order_born[str(order.client_order_id)] = now
        self.submit_order(order)

    def _maker_price(self, iid, side):
        """Цена мейкер-заявки: у своего края стакана."""
        q = self.cache.quote(iid)
        return q.bid_price if side == OrderSide.BUY else q.ask_price

    def _heartbeat(self) -> None:
        pos = {sym_of(i): float(self.portfolio.net_position(i)) for i in self.cfg.instrument_ids}
        hb = {
            "ts": int(self._now() * 1000),
            "positions": {k: v for k, v in pos.items() if v},
            # Нереализованный результат по открытым позициям — для /status в Telegram.
            "upnl": {
                sym_of(i): round(float(self.portfolio.unrealized_pnl(i) or 0), 2)
                for i in self.cfg.instrument_ids
                if pos[sym_of(i)]
            },
            "pnl": round(self._pnl(), 4),
            "day_pnl": round(self.carry + self._pnl() - self.day_start_pnl, 4),
            "halted": self.halted,
            "blocked": self.blocked,
            "open_orders": len(self.cache.orders_open()),
        }
        self.r.set(keys.HB_ACCOUNT.format(id=self.cfg.account_id), json.dumps(hb), ex=120)
        self.r.publish(keys.LIVE.format(id=self.cfg.account_id), json.dumps({"type": "hb", **hb}))


def apply_fill(q: float, avg: float, sign: float, qty: float, px: float):
    """Сделка против позиции по средней цене входа (линейный контракт в USDT).

    → (новая позиция, новая средняя, закрытый объём, результат закрытой части
    до комиссии).
    """
    if q == 0 or (q > 0) == (sign > 0):
        new = q + sign * qty
        return new, (abs(q) * avg + qty * px) / abs(new), 0.0, 0.0
    closed = min(abs(q), qty)
    gross = (px - avg) * closed * (1.0 if q > 0 else -1.0)
    new = q + sign * qty
    if abs(new) < 1e-9:
        return 0.0, 0.0, closed, gross
    return new, (avg if (new > 0) == (q > 0) else px), closed, gross


def _secs(s: int):
    import datetime as dt

    return dt.timedelta(seconds=s)
