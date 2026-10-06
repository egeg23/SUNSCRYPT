"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { EquityChart, type Fill } from "@/components/EquityChart";
import { Footer } from "@/components/Footer";
import { Header } from "@/components/Header";
import { RiskNote } from "@/components/RiskNote";
import { ApiError, api } from "@/lib/api";

type Account = { id: string; name: string; mode: "demo" | "real"; trading_enabled: boolean };
type Round = { sym: string; side: string; opened: number; closed: number | null; pnl: number; fees: number; net: number };
type Stats = {
  fills: number;
  rounds_closed: number;
  rounds_open: number;
  win_rate: number | null;
  avg_result: number | null;
  gross_pnl: number;
  fees: number;
  funding: number;
  net_pnl: number;
  equity_start: number | null;
  equity_now: number | null;
  max_drawdown: number | null;
  rounds: Round[];
};
type Hb = { ts: number; positions: Record<string, number>; pnl: number; day_pnl?: number; halted: string | null };
type Dash = {
  mode: "demo" | "real";
  stats: Stats;
  equity: [number, number][];
  heartbeat: Hb | null;
  fills: (Fill & { fee: number; liquidity: string | null })[];
};

const usd = (n: number | null | undefined, sign = false) =>
  n === null || n === undefined
    ? "—"
    : (sign && n > 0 ? "+" : n < 0 ? "−" : "") +
      Math.abs(n).toLocaleString("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) +
      " $";
const pct = (n: number | null | undefined, sign = false) =>
  n === null || n === undefined
    ? "—"
    : (sign && n > 0 ? "+" : n < 0 ? "−" : "") +
      Math.abs(n * 100).toLocaleString("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) +
      " %";
const tone = (n: number | null | undefined) => (n === null || n === undefined || n === 0 ? undefined : n > 0 ? "var(--gain)" : "var(--loss)");
const time = (ms: number) => new Date(ms).toLocaleString("ru-RU", { dateStyle: "short", timeStyle: "medium" });

function Tile({ label, value, sub, color }: { label: string; value: string; sub?: string; color?: string }) {
  return (
    <div className="card" style={{ padding: 16 }}>
      <div className="muted" style={{ fontSize: 13 }}>{label}</div>
      <div className="mono" style={{ fontSize: "clamp(17px, 2vw, 20px)", fontWeight: 600, marginTop: 4, whiteSpace: "nowrap", color: color ?? "var(--text)" }}>{value}</div>
      {sub ? <div className="muted" style={{ fontSize: 12, marginTop: 2 }}>{sub}</div> : null}
    </div>
  );
}

export default function DashboardPage() {
  const router = useRouter();
  const [accounts, setAccounts] = useState<Account[] | null>(null);
  const [sel, setSel] = useState<string | null>(null);
  const [mode, setMode] = useState<"demo" | "real" | null>(null);
  const [dash, setDash] = useState<Dash | null>(null);
  const [live, setLive] = useState(false);
  const [flash, setFlash] = useState<string | null>(null);
  const reloadTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    api<Account[]>("/accounts")
      .then((a) => {
        setAccounts(a);
        if (a.length) {
          setSel(a[0].id);
          setMode(a[0].mode);
        }
      })
      .catch((e) => {
        if (e instanceof ApiError && e.status === 401) router.replace("/login");
      });
  }, [router]);

  const load = useCallback(async () => {
    if (!sel || !mode) return;
    setDash(await api<Dash>(`/accounts/${sel}/dashboard?mode=${mode}`));
  }, [sel, mode]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- загрузка данных при выборе кабинета
    load().catch(() => {});
    const t = setInterval(() => load().catch(() => {}), 60000);
    return () => clearInterval(t);
  }, [load]);

  // Реальное время: события прямо из движка (SSE).
  useEffect(() => {
    if (!sel) return;
    const es = new EventSource(`/api/accounts/${sel}/live`);
    es.onopen = () => setLive(true);
    es.onerror = () => setLive(false);
    es.addEventListener("hb", (e) => {
      const hb = JSON.parse((e as MessageEvent).data) as Hb;
      setDash((d) => (d && d.mode === mode ? { ...d, heartbeat: hb } : d));
    });
    es.addEventListener("fill", (e) => {
      const f = JSON.parse((e as MessageEvent).data);
      if (f.mode !== mode) return;
      const fill = { ts: Number(f.ts), sym: f.sym, side: f.side, qty: Number(f.qty), price: Number(f.price), fee: Number(f.fee), liquidity: f.liquidity };
      setDash((d) => {
        if (!d) return d;
        const last = d.equity.at(-1);
        return { ...d, fills: [fill, ...d.fills], equity: last ? [...d.equity, [fill.ts, last[1]]] : d.equity };
      });
      setFlash(`${fill.side === "buy" ? "Покупка" : "Продажа"} ${fill.qty} ${fill.sym} по ${fill.price}`);
      // Статистика пересчитается, когда сделка ляжет в журнал.
      if (reloadTimer.current) clearTimeout(reloadTimer.current);
      reloadTimer.current = setTimeout(() => load().catch(() => {}), 12000);
    });
    return () => es.close();
  }, [sel, mode, load]);

  const s = dash?.stats;
  const growth = s && s.equity_start !== null && s.equity_now !== null ? s.equity_now - s.equity_start : null;
  const hb = dash?.heartbeat;

  return (
    <main className="wrap">
      <Header />
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap", alignItems: "baseline" }}>
        <h1 style={{ fontSize: 28 }}>Дашборд</h1>
        <span className="pill">
          <span className={live ? "dot ok" : "dot"} aria-hidden />
          {live ? "в реальном времени" : "нет связи с движком"}
        </span>
      </div>

      {accounts && !accounts.length ? (
        <p className="muted">
          Кабинетов пока нет. <Link href="/accounts">Подключить кабинет →</Link>
        </p>
      ) : null}

      {accounts && accounts.length ? (
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", margin: "8px 0 16px" }}>
          <span className="muted" style={{ fontSize: 14 }}>Кабинет:</span>
          {accounts.length > 1 ? (
            <select
              value={sel ?? ""}
              onChange={(e) => {
                const a = accounts.find((x) => x.id === e.target.value)!;
                setSel(a.id);
                setMode(a.mode);
              }}
              style={{ font: "inherit", padding: "8px 10px", borderRadius: 10, background: "var(--surface)", color: "var(--text)", border: "1px solid var(--line)" }}
            >
              {accounts.map((a) => (
                <option key={a.id} value={a.id}>{a.name}</option>
              ))}
            </select>
          ) : (
            <b style={{ fontSize: 14 }}>{accounts[0].name}</b>
          )}
          <span className="muted" style={{ fontSize: 14, marginLeft: 8 }}>Счёт:</span>
          {(["demo", "real"] as const).map((m) => (
            <button
              key={m}
              className="btn ghost"
              aria-pressed={mode === m}
              style={{ padding: "6px 14px", fontSize: 14, background: mode === m ? "var(--surface-2)" : "transparent" }}
              onClick={() => setMode(m)}
            >
              {m === "demo" ? "Демо" : "Реальный"}
            </button>
          ))}
        </div>
      ) : null}

      <p className="muted" style={{ fontSize: 13, maxWidth: 760 }}>
        Все цифры — после комиссий и фандинга, за последние 30 дней. {dash?.mode === "demo" ? "Это демо-счёт: деньги ненастоящие. " : ""}
        Прошлые результаты не обещают будущих.
      </p>

      {flash ? (
        <div className="card" role="status" style={{ borderColor: "var(--accent)", marginBottom: 12, fontSize: 14 }}>
          Новая сделка: <b>{flash}</b>
        </div>
      ) : null}

      {s ? (
        <>
          <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 12 }}>
            <Tile label="Баланс счёта" value={usd(s.equity_now)} sub={s.equity_start !== null ? `начальный ${usd(s.equity_start)}` : undefined} />
            <Tile label="Рост от начального" value={usd(growth, true)} color={tone(growth)} sub={growth !== null && s.equity_start ? pct(growth / s.equity_start, true) : undefined} />
            <Tile label="Результат стратегии" value={usd(s.net_pnl, true)} color={tone(s.net_pnl)} sub="по закрытым сделкам, после комиссий" />
            <Tile label="Успешных сделок" value={s.win_rate === null ? "—" : `${Math.round(s.win_rate * 100)} %`} sub={`закрыто ${s.rounds_closed}, открыто ${s.rounds_open}`} />
            <Tile label="Средний результат" value={usd(s.avg_result, true)} color={tone(s.avg_result)} sub="на закрытую сделку" />
            <Tile label="Макс. просадка" value={pct(s.max_drawdown)} />
            <Tile label="Комиссии" value={usd(-s.fees)} sub={`исполнений: ${s.fills}`} />
            <Tile label="Фандинг" value={usd(-s.funding)} />
          </div>

          <section>
            <h2>Баланс счёта</h2>
            <div className="card" style={{ padding: 12 }}>
              {dash!.equity.length ? (
                <EquityChart equity={dash!.equity} fills={dash!.fills} />
              ) : (
                <p className="muted">Снимки баланса появятся через минуту после включения торговли.</p>
              )}
            </div>
            <p className="muted" style={{ fontSize: 12 }}>Стрелки — сделки: ▲ покупка, ▼ продажа. Снимок баланса — раз в минуту и на каждую сделку.</p>
          </section>

          <section>
            <h2>Открытые позиции</h2>
            {hb ? (
              <>
                {Object.keys(hb.positions).length ? (
                  <div className="table-wrap">
                    <table className="log">
                      <thead><tr><th>Пара</th><th>Позиция</th></tr></thead>
                      <tbody>
                        {Object.entries(hb.positions).map(([sym, q]) => (
                          <tr key={sym}>
                            <td className="mono">{sym}</td>
                            <td className="mono" style={{ color: q > 0 ? "var(--gain)" : "var(--loss)" }}>{q > 0 ? `▲ лонг ${q}` : `▼ шорт ${-q}`}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <p className="muted">Позиций нет.</p>
                )}
                <p className="muted" style={{ fontSize: 12 }}>
                  Обновлено {time(hb.ts)}{hb.day_pnl !== undefined ? ` · за сутки (UTC): ${usd(hb.day_pnl, true)}` : ""}
                  {hb.halted ? ` · стоит: ${hb.halted}` : ""}
                </p>
              </>
            ) : (
              <p className="muted">Движок по этому счёту сейчас не работает.</p>
            )}
          </section>

          <section>
            <h2>Сделки</h2>
            {s.rounds.length ? (
              <div className="table-wrap">
                <table className="log">
                  <thead><tr><th>Пара</th><th>Направление</th><th>Открыта</th><th>Закрыта</th><th>По ценам</th><th>Комиссии</th><th>Итог</th></tr></thead>
                  <tbody>
                    {s.rounds.map((r, i) => (
                      <tr key={i}>
                        <td className="mono">{r.sym}</td>
                        <td>{r.side === "long" ? "▲ лонг" : "▼ шорт"}</td>
                        <td className="mono">{time(r.opened)}</td>
                        <td className="mono">{r.closed ? time(r.closed) : "открыта"}</td>
                        <td className="mono">{usd(r.pnl, true)}</td>
                        <td className="mono">{usd(-r.fees)}</td>
                        <td className="mono" style={{ color: r.closed ? tone(r.net) : undefined }}>{r.closed ? usd(r.net, true) : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="muted">Сделок пока нет.</p>
            )}
          </section>

          <section>
            <h2>Лента исполнений</h2>
            {dash!.fills.length ? (
              <div className="table-wrap">
                <table className="log">
                  <thead><tr><th>Время</th><th>Пара</th><th>Сторона</th><th>Кол-во</th><th>Цена</th><th>Комиссия</th></tr></thead>
                  <tbody>
                    {dash!.fills.slice(0, 50).map((f, i) => (
                      <tr key={i}>
                        <td className="mono">{time(f.ts)}</td>
                        <td className="mono">{f.sym}</td>
                        <td style={{ color: f.side === "buy" ? "var(--gain)" : "var(--loss)" }}>{f.side === "buy" ? "▲ покупка" : "▼ продажа"}</td>
                        <td className="mono">{f.qty}</td>
                        <td className="mono">{f.price}</td>
                        <td className="mono">{f.fee.toFixed(4)}{f.liquidity === "MAKER" ? " · мейкер" : f.liquidity === "TAKER" ? " · тейкер" : ""}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="muted">Исполнений пока нет.</p>
            )}
          </section>
        </>
      ) : accounts?.length ? (
        <p className="muted">Загрузка…</p>
      ) : null}
      <RiskNote />
      <Footer />
    </main>
  );
}
