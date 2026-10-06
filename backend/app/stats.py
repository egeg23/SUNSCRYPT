"""Честная статистика кабинета (бриф, этап 6): всё после комиссий и
фандинга.

Сделка (раунд) — от открытия позиции по паре до её закрытия; результат
раунда — разница цен по исполнениям минус все комиссии раунда. Успешность —
доля раундов с результатом > 0. Просадка — по снимкам баланса."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Round:
    sym: str
    side: str  # long | short
    opened: int  # ms
    closed: int | None = None
    pnl: float = 0.0  # по ценам
    fees: float = 0.0

    @property
    def net(self) -> float:
        return self.pnl - self.fees


@dataclass
class Book:
    """Позиция по паре: средняя цена входа и количество со знаком."""

    qty: float = 0.0
    avg: float = 0.0
    rnd: Round | None = None
    rounds: list[Round] = field(default_factory=list)


EPS = 1e-12


def rounds_from_fills(fills: list[dict]) -> list[Round]:
    """fills: {sym, side: buy|sell, qty, price, fee, ts(ms)} по времени."""
    books: dict[str, Book] = {}
    out: list[Round] = []
    for f in sorted(fills, key=lambda x: x["ts"]):
        b = books.setdefault(f["sym"], Book())
        q = f["qty"] if f["side"] == "buy" else -f["qty"]
        px, fee = f["price"], f["fee"]
        if abs(b.qty) < EPS:
            b.qty, b.avg = q, px
            b.rnd = Round(f["sym"], "long" if q > 0 else "short", f["ts"], fees=fee)
            continue
        assert b.rnd is not None
        b.rnd.fees += fee
        if (b.qty > 0) == (q > 0):  # добор
            b.avg = (b.avg * abs(b.qty) + px * abs(q)) / (abs(b.qty) + abs(q))
            b.qty += q
            continue
        closing = min(abs(q), abs(b.qty))
        b.rnd.pnl += closing * (px - b.avg) * (1 if b.qty > 0 else -1)
        rest = b.qty + q
        if abs(rest) < EPS or (rest > 0) != (b.qty > 0):
            b.rnd.closed = f["ts"]
            out.append(b.rnd)
            b.rnd = None
            if abs(rest) > EPS:  # переворот — новый раунд с остатком
                b.rnd = Round(f["sym"], "long" if rest > 0 else "short", f["ts"])
                b.avg = px
            b.qty = rest
        else:
            b.qty = rest
    out += [b.rnd for b in books.values() if b.rnd is not None]  # открытые
    return out


def max_drawdown(series: list[float]) -> float:
    """Максимальная просадка в долях от пика."""
    peak, dd = 0.0, 0.0
    for v in series:
        peak = max(peak, v)
        if peak > 0:
            dd = max(dd, (peak - v) / peak)
    return dd


def summarize(fills: list[dict], funding: list[float], equity: list[float]) -> dict:
    rounds = rounds_from_fills(fills)
    closed = [r for r in rounds if r.closed is not None]
    wins = [r for r in closed if r.net > 0]
    fees = sum(f["fee"] for f in fills)
    fund = sum(funding)
    gross = sum(r.pnl for r in closed)
    return {
        "fills": len(fills),
        "rounds_closed": len(closed),
        "rounds_open": len(rounds) - len(closed),
        "win_rate": len(wins) / len(closed) if closed else None,
        "avg_result": (sum(r.net for r in closed) / len(closed)) if closed else None,
        "gross_pnl": gross,
        "fees": fees,
        "funding": fund,
        # Комиссии всех исполнений (и у открытых раундов) и фандинг — вычтены.
        "net_pnl": gross - fees - fund,
        "equity_start": equity[0] if equity else None,
        "equity_now": equity[-1] if equity else None,
        "max_drawdown": max_drawdown(equity) if equity else None,
        "rounds": [
            {
                "sym": r.sym,
                "side": r.side,
                "opened": r.opened,
                "closed": r.closed,
                "pnl": r.pnl,
                "fees": r.fees,
                "net": r.net,
            }
            for r in sorted(rounds, key=lambda r: r.opened, reverse=True)[:50]
        ],
    }
