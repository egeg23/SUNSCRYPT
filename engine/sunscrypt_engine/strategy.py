"""Kronos signal as a NautilusTrader (2.x) strategy.

Every `horizon` closed bars the strategy asks a signal source for (rhat, pup, sd) per instrument, debiases rhat
with its trailing mean/std over the last `z_window` decisions (z-score, past only) and targets
+1 / -1 / 0 x `notional_usd` when |z| > `z_threshold`. Execution: market orders (taker) or post-only limits at the
last close (maker). Nautilus handles orders, positions, reconciliation, fees and the venue connection.
"""
from __future__ import annotations

import os
from collections import defaultdict, deque
from decimal import Decimal

import numpy as np

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model import Bar, BarType, InstrumentId, OrderSide, TimeInForce
from nautilus_trader.trading import Strategy


class KronosStrategyConfig(StrategyConfig):
    def __init__(self, *, instrument_ids: list[InstrumentId], bar_types: list[BarType], signal_source,
                 horizon: int = 8, context: int = 256, bar_minutes: int = 60, z_window: int = 30,
                 z_min_periods: int = 10, z_threshold: float = 1.0, use_z: bool = True, notional_usd: float = 100.0,
                 trade_after_ns: int = 0, execution: str = "taker", maker_offset_bps: float = 1.0, max_daily_loss_usd: float = 50.0, kill_file: str = "KILL",
                 **_kwargs: object) -> None:
        super().__init__()
        self.instrument_ids = instrument_ids
        self.bar_types = bar_types
        self.signal_source = signal_source
        self.horizon = horizon
        self.context = context
        self.bar_minutes = bar_minutes
        self.z_window = z_window
        self.z_min_periods = z_min_periods
        self.z_threshold = z_threshold
        self.use_z = use_z
        self.notional_usd = notional_usd
        self.execution = execution
        self.trade_after_ns = trade_after_ns
        self.maker_offset_bps = maker_offset_bps
        self.max_daily_loss_usd = max_daily_loss_usd
        self.kill_file = kill_file


class KronosStrategy(Strategy):
    def __init__(self, config: KronosStrategyConfig) -> None:
        super().__init__(config)
        self.cfg = config
        self.bars = defaultdict(lambda: deque(maxlen=config.context + 8))
        self.rhat_hist = defaultdict(lambda: deque(maxlen=config.z_window))
        self.by_bar_type = {str(bt): iid for bt, iid in zip(config.bar_types, config.instrument_ids)}
        self.day, self.day_start_pnl, self.halted = None, 0.0, False
        self.realized = 0.0
        self.decisions = []          # (ts, instrument, rhat, z, target) for the journal

    # ---------------------------------------------------------------- lifecycle
    def on_start(self) -> None:
        for bt in self.cfg.bar_types:
            if getattr(self.cfg.signal_source, "needs_history", False):
                self.request_bars(bt, limit=self.cfg.context + 2)
            self.subscribe_bars(bt)

    def on_stop(self) -> None:
        for iid in self.cfg.instrument_ids:
            self.cancel_all_orders(iid)
            self.close_all_positions(iid)

    def on_historical_data(self, data) -> None:
        if isinstance(data, Bar):
            self._store(data)

    def on_position_closed(self, event) -> None:
        self.realized += float(event.realized_pnl)

    # ---------------------------------------------------------------- bars
    def _store(self, bar: Bar) -> InstrumentId:
        iid = self.by_bar_type[str(bar.bar_type)]
        buf = self.bars[iid]
        if buf and buf[-1][0] >= bar.ts_event:
            return iid
        buf.append((bar.ts_event, float(bar.open), float(bar.high), float(bar.low), float(bar.close),
                    float(bar.volume)))
        return iid

    def on_bar(self, bar: Bar) -> None:
        iid = self._store(bar)
        if bar.ts_event <= self.cfg.trade_after_ns:      # warm-up bars: only fill the buffer
            return
        if self._risk_halt(bar.ts_event):
            return
        close_min = bar.ts_event // 60_000_000_000                # ts_event = bar close time
        if (close_min // self.cfg.bar_minutes) % self.cfg.horizon:
            return
        sig = self.cfg.signal_source.signal(iid, bar.ts_event, self.bars[iid])
        if sig is None:
            return
        rhat = sig[0]
        hist = self.rhat_hist[iid]
        z = 0.0
        if len(hist) >= self.cfg.z_min_periods:
            h = np.asarray(hist)
            sd = h.std(ddof=1)
            z = (rhat - h.mean()) / sd if sd > 0 else 0.0
        hist.append(rhat)
        if self.cfg.use_z:
            target = float(np.sign(z)) if abs(z) > self.cfg.z_threshold else 0.0
        else:
            target = float(np.sign(rhat))                             # raw sign, always in the market
        self.decisions.append((bar.ts_event, str(iid), rhat, z, target))
        self._rebalance(iid, target, float(bar.close))

    # ---------------------------------------------------------------- orders
    def _rebalance(self, iid: InstrumentId, target: float, price: float) -> None:
        inst = self.cache.instrument(iid)
        cur = float(self.portfolio.net_position(iid))
        want = target * self.cfg.notional_usd / price
        step = float(inst.size_increment)
        delta = round((want - cur) / step) * step
        if cur and target and np.sign(cur) == np.sign(target) and abs(delta) < 0.25 * abs(cur):
            return                                                 # hysteresis: skip tiny resizes
        if abs(delta) < step / 2:
            return
        self.cancel_all_orders(iid)
        side = OrderSide.BUY if delta > 0 else OrderSide.SELL
        qty = inst.make_qty(Decimal(str(abs(delta))))
        reduce_only = target == 0 or (cur != 0 and abs(want) < abs(cur) and np.sign(want) == np.sign(cur))
        if self.cfg.execution == "maker":
            off = self.cfg.maker_offset_bps / 10_000            # rest just inside our side of the book
            px = price * (1 - off) if side == OrderSide.BUY else price * (1 + off)
            order = self.order_factory.limit(iid, side, qty, inst.make_price(px), post_only=True,
                                             reduce_only=reduce_only, time_in_force=TimeInForce.GTC)
        else:
            order = self.order_factory.market(iid, side, qty, reduce_only=reduce_only)
        self.submit_order(order)

    # ---------------------------------------------------------------- risk
    def _risk_halt(self, ts: int) -> bool:
        if os.path.exists(self.cfg.kill_file):
            if not self.halted:
                self.log.warning("kill switch file found: flattening and halting")
                self.on_stop()
            self.halted = True
            return True
        day = ts // 86_400_000_000_000
        unreal = sum(float(self.portfolio.unrealized_pnl(i) or 0) for i in self.cfg.instrument_ids)
        pnl = self.realized + unreal
        if day != self.day:
            self.day, self.day_start_pnl = day, pnl
            if self.halted:
                self.log.info("new UTC day: daily-loss halt lifted")
            self.halted = False
        if not self.halted and pnl - self.day_start_pnl < -self.cfg.max_daily_loss_usd:
            self.log.warning(f"daily loss limit hit ({pnl - self.day_start_pnl:.2f} USD): flattening")
            self.on_stop()
            self.halted = True
        return self.halted
