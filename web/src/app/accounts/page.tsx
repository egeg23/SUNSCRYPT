"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { Footer } from "@/components/Footer";
import { Header } from "@/components/Header";
import { RiskNote } from "@/components/RiskNote";
import { ApiError, api, type Me } from "@/lib/api";
import { useSubmit } from "@/lib/useForm";

type Account = {
  id: string;
  name: string;
  mode: "demo" | "real";
  key_tail: string;
  permissions: Record<string, string[]>;
  ips: string[];
  warnings: string[];
  status: "ok" | "error";
  status_detail: string | null;
  equity_usd: number | null;
  stopped: boolean;
  checked_at: string | null;
  trading_enabled: boolean;
  leverage: number;
  capital_usd: number | null;
  daily_loss_pct: number;
  max_drawdown_pct: number;
  keys: Record<"demo" | "real", { key_tail: string; status: string; status_detail: string | null; equity_usd: number | null } | null>;
};

type Engine = {
  heartbeat: {
    ts: number;
    positions: Record<string, number>;
    pnl: number;
    halted: string | null;
    open_orders: number;
  } | null;
  drawdown_halt: string | null;
  reconcile: { ts: number; bybit: number; journal: number; added: number; extra: number } | null;
  equity: { ts: string; usd: number } | null;
  trades: { ts: string; sym: string; side: string; qty: number; price: number; fee: number; liquidity: string | null; source: string }[];
  events: { ts: string; kind: string; message: string }[];
};

type Signal = {
  sym: string;
  ts_close: number;
  rhat: number;
  z: number;
  target: number;
  horizon: number;
  model: string;
  paused?: boolean;
};
type Signals = { alive: boolean; config: string | null; signals: Signal[] };

const REPORT = "https://github.com/egeg23/SUNSCRYPT/blob/main/engine/research/selection/REPORT.md";

const when = (s: string | number) => new Date(s).toLocaleString("ru-RU", { dateStyle: "short", timeStyle: "short" });

function Signals() {
  const [data, setData] = useState<Signals | null>(null);
  useEffect(() => {
    const load = () => api<Signals>("/engine/signals").then(setData).catch(() => {});
    load();
    const t = setInterval(load, 30000);
    return () => clearInterval(t);
  }, []);
  if (!data) return null;
  return (
    <section>
      <h2>Сигналы</h2>
      <p className="muted" style={{ fontSize: 14, maxWidth: 720 }}>
        Одни на всех. Пары и стратегия каждой — по итогам отбора на истории после комиссий
        {data.config ? ` (версия ${data.config})` : ""}:{" "}
        <a href={REPORT} target="_blank" rel="noreferrer">
          отчёт с цифрами и оговорками
        </a>
        . Моментум — раз в сутки в 00:00 UTC позиция по знаку движения цены за 24 часа; Kronos — раз в 8
        часов по прогнозу модели. Прошлые результаты не обещают будущих: на истории просадки по паре
        доходили до 43–71%.
      </p>
      {!data.alive ? (
        <p className="err">Сервис сигналов не отвечает.</p>
      ) : data.signals.length === 0 ? (
        <p className="muted">Первые решения появятся на ближайшем окне решения.</p>
      ) : (
        <div className="table-wrap">
          <table className="log">
            <thead>
              <tr><th>Пара</th><th>Стратегия</th><th>Решение от</th><th>Основание</th><th>Позиция</th></tr>
            </thead>
            <tbody>
              {data.signals.map((s) => (
                <tr key={s.sym}>
                  <td className="mono">{s.sym}</td>
                  <td>{s.model === "momentum_4h" ? "моментум" : `Kronos (${s.model})`}</td>
                  <td className="mono">{when(s.ts_close)}</td>
                  <td className="mono">
                    {s.model === "momentum_4h"
                      ? `за 24 ч ${(s.rhat * 100).toFixed(2)} %`
                      : `прогноз ${(s.rhat * 100).toFixed(2)} %, z ${s.z.toFixed(2)}`}
                  </td>
                  <td style={{ color: s.target > 0 ? "var(--gain)" : s.target < 0 ? "var(--loss)" : "var(--muted)" }}>
                    {s.paused ? "⏸ пауза (дрейф)" : s.target > 0 ? "▲ лонг" : s.target < 0 ? "▼ шорт" : "— вне рынка"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function EnginePanel({ a }: { a: Account }) {
  const [e, setE] = useState<Engine | null>(null);
  useEffect(() => {
    const load = () => api<Engine>(`/accounts/${a.id}/engine`).then(setE).catch(() => {});
    load();
    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, [a.id]);
  if (!e) return null;
  const hb = e.heartbeat;
  const resetDrawdown = async () => {
    let code: string | null = null;
    if (a.mode === "real") {
      code = prompt("Реальный счёт: код 2FA, чтобы снять остановку по просадке");
      if (!code) return;
    } else if (!confirm("Снять остановку по просадке? Торговля продолжится, просадка дальше считается от текущего результата.")) return;
    await api(`/accounts/${a.id}/drawdown-reset`, { code });
    setE(await api<Engine>(`/accounts/${a.id}/engine`));
  };
  // eslint-disable-next-line react-hooks/purity -- возраст сердцебиения считается при каждой отрисовке
  const alive = hb !== null && Date.now() - hb.ts < 60000;
  return (
    <div style={{ fontSize: 14, display: "grid", gap: 6, borderTop: "1px solid var(--line)", paddingTop: 10 }}>
      <div>
        Движок:{" "}
        {alive ? (
          hb!.halted ? <span style={{ color: "var(--loss)" }}>стоит — {hb!.halted}</span> : <span style={{ color: "var(--gain)" }}>● работает</span>
        ) : a.trading_enabled ? (
          <span className="muted">запускается…</span>
        ) : (
          <span className="muted">выключен</span>
        )}
      </div>
      {e.drawdown_halt ? (
        <div className="err" style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <span>⏹ Остановлен по лимиту просадки: {e.drawdown_halt}.</span>
          <button className="btn ghost" style={{ padding: "4px 10px", fontSize: 13 }} onClick={resetDrawdown}>
            Снять и продолжить
          </button>
        </div>
      ) : null}
      {alive ? (
        <div className="muted">
          Позиции:{" "}
          {Object.keys(hb!.positions).length
            ? Object.entries(hb!.positions).map(([s, q]) => `${s} ${q > 0 ? "+" : ""}${q}`).join(", ")
            : "нет"}
          {" · "}PnL с запуска: <span className="mono">{hb!.pnl >= 0 ? "+" : ""}{hb!.pnl.toFixed(2)} USD</span>
        </div>
      ) : null}
      {e.reconcile ? (
        <div className="muted" style={{ fontSize: 12 }}>
          Сверка с Bybit {when(e.reconcile.ts)}: у Bybit {e.reconcile.bybit}, в журнале {e.reconcile.journal}
          {e.reconcile.added || e.reconcile.extra ? `, расхождений ${e.reconcile.added + e.reconcile.extra}` : " — сходится"}
        </div>
      ) : null}
      {e.trades.length ? (
        <details>
          <summary>Сделки ({e.trades.length})</summary>
          <div className="table-wrap">
            <table className="log">
              <thead><tr><th>Время</th><th>Пара</th><th>Сторона</th><th>Кол-во</th><th>Цена</th><th>Комиссия</th></tr></thead>
              <tbody>
                {e.trades.map((t, i) => (
                  <tr key={i}>
                    <td className="mono">{when(t.ts)}</td>
                    <td className="mono">{t.sym}</td>
                    <td style={{ color: t.side === "buy" ? "var(--gain)" : "var(--loss)" }}>{t.side === "buy" ? "покупка" : "продажа"}</td>
                    <td className="mono">{t.qty}</td>
                    <td className="mono">{t.price}</td>
                    <td className="mono">{t.fee.toFixed(4)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      ) : null}
      {e.events.length ? (
        <details>
          <summary>События движка</summary>
          <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
            {e.events.slice(0, 10).map((ev, i) => (
              <li key={i} className="muted">
                <span className="mono">{when(ev.ts)}</span> — {ev.message}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </div>
  );
}

function TradingSettings({ a, reload }: { a: Account; reload: () => void }) {
  const { busy, error, run } = useSubmit();
  return (
    <form
      className="form"
      style={{ borderTop: "1px solid var(--line)", paddingTop: 10, gap: 10 }}
      onSubmit={(ev) => {
        ev.preventDefault();
        const f = new FormData(ev.currentTarget);
        run(async () => {
          await api(`/accounts/${a.id}/settings`, {
            leverage: Number(f.get("leverage")),
            capital_usd: f.get("capital_usd") ? Number(f.get("capital_usd")) : null,
            daily_loss_pct: Number(f.get("daily_loss_pct")),
            max_drawdown_pct: Number(f.get("max_drawdown_pct")),
          }, "PATCH");
          reload();
        });
      }}
    >
      <div style={{ display: "grid", gap: 10, gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))" }}>
        <label>
          Капитал, USD
          <input name="capital_usd" type="number" min={50} step={50} defaultValue={a.capital_usd ?? ""} placeholder="до 1000" />
        </label>
        <label>
          Плечо
          <select name="leverage" defaultValue={String(a.leverage)} style={{ font: "inherit", padding: "10px", borderRadius: 10, background: "var(--surface)", color: "var(--text)", border: "1px solid var(--line)" }}>
            <option value="1">1× (рекомендуем)</option>
            <option value="1.5">1.5×</option>
            <option value="2">2× (максимум)</option>
          </select>
        </label>
        <label>
          Дневной лимит убытка, %
          <input name="daily_loss_pct" type="number" min={0.5} max={50} step={0.5} defaultValue={a.daily_loss_pct} />
        </label>
        <label title="Просадка от пика результата стратегии в % капитала. Сработал — позиции закрываются, торговля стоит до вашего решения.">
          Лимит просадки, %
          <input name="max_drawdown_pct" type="number" min={5} max={60} step={1} defaultValue={a.max_drawdown_pct} />
        </label>
      </div>
      {error ? <p className="err">{error}</p> : null}
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <button className="btn ghost" disabled={busy}>Сохранить настройки</button>
        <button
          type="button"
          className="btn"
          disabled={busy || a.status !== "ok" || a.stopped}
          onClick={() => run(async () => { await api(`/accounts/${a.id}/settings`, { trading_enabled: !a.trading_enabled }, "PATCH"); reload(); })}
          style={a.trading_enabled ? { background: "var(--surface-2)", color: "var(--text)" } : undefined}
        >
          {a.trading_enabled ? "Выключить торговлю" : "Включить торговлю"}
        </button>
      </div>
      <p className="muted" style={{ fontSize: 12, margin: 0 }}>
        Капитал — сколько из баланса отдаётся стратегии; он делится поровну между парами. При убытке за
        сутки больше лимита движок закрывает позиции до конца суток (UTC).
      </p>
    </form>
  );
}

const money = (n: number | null) =>
  n === null ? "—" : n.toLocaleString("ru-RU", { maximumFractionDigits: 2 }) + " USD";

function Copy({ text }: { text: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      type="button"
      className="btn ghost"
      style={{ padding: "4px 10px", fontSize: 13 }}
      onClick={async () => {
        await navigator.clipboard.writeText(text);
        setDone(true);
      }}
    >
      {done ? "Скопировано" : "Копировать"}
    </button>
  );
}

function Steps({ mode, ip }: { mode: "demo" | "real"; ip: string }) {
  return (
    <ol style={{ paddingLeft: 20, margin: "0 0 16px", display: "grid", gap: 8, fontSize: 15 }}>
      <li>
        Войдите на{" "}
        <a href="https://www.bybit.com" target="_blank" rel="noreferrer">
          bybit.com
        </a>
        . Нужна включённая 2FA (Google Authenticator) — без неё Bybit не даст создать ключ.
      </li>
      {mode === "demo" ? (
        <li>
          Включите демо-режим: аватар в правом верхнем углу → <b>Demo Trading</b>. У демо-счёта
          свои ключи — создавать нужно, не выходя из этого режима.
        </li>
      ) : (
        <li>
          Убедитесь, что вы на <b>основном</b> счёте (не Demo Trading) и счёт — единый торговый
          (Unified Trading Account).
        </li>
      )}
      <li>
        Аватар → <b>API</b> (или{" "}
        <a href="https://www.bybit.com/app/user/api-management" target="_blank" rel="noreferrer">
          страница ключей
        </a>
        ) → <b>Create New Key</b> → <b>System-generated API Keys</b>.
      </li>
      <li>
        Назначение — <b>API Transaction</b>, название — например «SUNSCRYPT», доступ —{" "}
        <b>Read-Write</b>.
      </li>
      <li>
        <b>IP access</b> → «Only IPs with permissions granted» → впишите IP нашего сервера:{" "}
        <code>{ip}</code> <Copy text={ip} />
      </li>
      <li>
        Права: только <b>Unified Trading → Contract → Orders</b> и <b>Positions</b>.{" "}
        <b style={{ color: "var(--loss)" }}>
          Не отмечайте Withdrawal (вывод), Transfer и Assets (переводы)
        </b>{" "}
        — ключ с такими правами сервис отклонит.
      </li>
      <li>
        <b>Submit</b>, код 2FA. Скопируйте <b>API Key</b> и <b>API Secret</b> кнопками Copy —
        секрет Bybit покажет только один раз. Вставьте их ниже.
      </li>
    </ol>
  );
}

function AddWizard({
  ip,
  onDone,
  accountId,
  fixedMode,
}: {
  ip: string;
  onDone: () => void;
  accountId?: string;
  fixedMode?: "demo" | "real";
}) {
  const [mode, setMode] = useState<"demo" | "real" | null>(fixedMode ?? null);
  const { busy, run } = useSubmit();
  const [result, setResult] = useState<{ problems: string[]; warnings: string[] } | null>(null);

  if (!mode) {
    return (
      <div className="grid">
        <button className="card" style={{ textAlign: "left", cursor: "pointer" }} onClick={() => setMode("demo")}>
          <h3>Демо-счёт · рекомендуем</h3>
          <p className="muted" style={{ fontSize: 14, margin: 0 }}>
            Ненастоящие деньги Bybit. Всё начинается здесь: проверить, как работает сервис, без риска.
          </p>
        </button>
        <button className="card" style={{ textAlign: "left", cursor: "pointer" }} onClick={() => setMode("real")}>
          <h3>Реальный счёт</h3>
          <p className="muted" style={{ fontSize: 14, margin: 0 }}>
            Ключ можно подключить заранее, но торговля на реальных деньгах пока выключена для всех и
            включится только отдельным решением владельца сервиса.
          </p>
        </button>
      </div>
    );
  }

  return (
    <div className="card">
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
        <h3>{mode === "demo" ? "Демо-счёт" : "Реальный счёт"}: создайте ключ на Bybit</h3>
        {fixedMode ? null : (
          <button className="btn ghost" style={{ padding: "4px 10px", fontSize: 13 }} onClick={() => setMode(null)}>
            ← другой счёт
          </button>
        )}
      </div>
      <Steps mode={mode} ip={ip} />
      <p style={{ fontSize: 14, color: "var(--accent)" }}>
        ⚠ Этот счёт Bybit — только для SUNSCRYPT. На Bybit по каждой паре одна позиция на счёт, и движок
        считает своими все позиции по торгуемым парам: сделки вручную или другим ботом на этом счёте он
        будет закрывать.
      </p>
      <form
        className="form"
        style={{ maxWidth: 480 }}
        onSubmit={(e) => {
          e.preventDefault();
          const f = new FormData(e.currentTarget);
          setResult(null);
          run(async () => {
            try {
              const clean = (v: FormDataEntryValue | null) => String(v).replace(/[^A-Za-z0-9]/g, "");
              if (accountId) {
                await api(`/accounts/${accountId}/keys`, {
                  mode,
                  api_key: clean(f.get("api_key")),
                  api_secret: clean(f.get("api_secret")),
                });
                onDone();
                return;
              }
              await api("/accounts", {
                name: String(f.get("name") || (mode === "demo" ? "Демо" : "Реальный")),
                mode,
                // Ключи Bybit — только латиница и цифры; телефон при копировании
                // может добавить пробелы и невидимые символы.
                api_key: String(f.get("api_key")).replace(/[^A-Za-z0-9]/g, ""),
                api_secret: String(f.get("api_secret")).replace(/[^A-Za-z0-9]/g, ""),
              });
              onDone();
            } catch (err) {
              if (err instanceof ApiError) {
                setResult({ problems: err.problems.length ? err.problems : [err.message], warnings: err.warnings });
              } else throw err;
            }
          });
        }}
      >
        {accountId ? null : (
          <label>
            Название кабинета
            <input name="name" maxLength={60} placeholder={mode === "demo" ? "Демо" : "Основной"} />
          </label>
        )}
        <label>
          API Key
          <input name="api_key" autoComplete="off" autoCapitalize="none" autoCorrect="off" spellCheck={false} required />
        </label>
        <label>
          API Secret
          <input name="api_secret" type="password" autoComplete="off" autoCapitalize="none" autoCorrect="off" spellCheck={false} required />
        </label>
        {result ? (
          <div className="err" role="alert">
            <b>Ключ не подходит:</b>
            <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
              {result.problems.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          </div>
        ) : null}
        <button className="btn" disabled={busy}>
          {busy ? "Проверяю ключ у Bybit…" : "Проверить и подключить"}
        </button>
        <p className="muted" style={{ fontSize: 13, margin: 0 }}>
          Ключ проверяется у Bybit только на чтение и хранится зашифрованным. Показать его ещё раз
          нельзя — ни вам, ни нам.
        </p>
      </form>
    </div>
  );
}

function ModeSwitch({ a, ip, realAllowed, reload }: { a: Account; ip: string; realAllowed: boolean; reload: () => void }) {
  const { busy, error, run } = useSubmit();
  const [want, setWant] = useState<"demo" | "real" | null>(null);
  const seg = (m: "demo" | "real", label: string) => (
    <button
      type="button"
      className="btn ghost"
      aria-pressed={a.mode === m}
      style={{
        padding: "6px 14px",
        fontSize: 14,
        background: a.mode === m ? (m === "real" ? "var(--loss)" : "var(--accent)") : "transparent",
        color: a.mode === m ? (m === "real" ? "#fff" : "#14171c") : "var(--text)",
      }}
      onClick={() => (a.mode === m ? setWant(null) : setWant(m))}
    >
      {label}
    </button>
  );
  return (
    <div style={{ display: "grid", gap: 8, borderTop: "1px solid var(--line)", paddingTop: 10 }}>
      <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
        <span className="muted" style={{ fontSize: 14 }}>Счёт:</span>
        {seg("demo", "Демо")}
        {seg("real", "Реальный")}
      </div>
      {want && !a.keys[want] ? (
        <AddWizard ip={ip} accountId={a.id} fixedMode={want} onDone={() => { setWant(null); reload(); }} />
      ) : null}
      {want === "demo" && a.keys.demo ? (
        <div className="card">
          <p style={{ fontSize: 14 }}>
            Перейти на демо-счёт? Если идёт торговля, движок закроет позиции на реальном счёте и продолжит на демо.
          </p>
          {error ? <p className="err">{error}</p> : null}
          <button className="btn" disabled={busy} onClick={() => run(async () => { await api(`/accounts/${a.id}/mode`, { mode: "demo" }); setWant(null); reload(); })}>
            Перейти на демо
          </button>
        </div>
      ) : null}
      {want === "real" && a.keys.real ? (
        !realAllowed ? (
          <p className="err">Торговля на реальном счёте пока выключена владельцем сервиса. Ключ подключён — переход станет доступен, когда её включат.</p>
        ) : (
          <form
            className="card form"
            onSubmit={(ev) => {
              ev.preventDefault();
              const f = new FormData(ev.currentTarget);
              run(async () => {
                await api(`/accounts/${a.id}/mode`, {
                  mode: "real",
                  confirm_risk: f.get("confirm") === "on",
                  capital_usd: Number(f.get("capital_usd")),
                  daily_loss_pct: Number(f.get("daily_loss_pct")),
                  code: String(f.get("code")).replace(/\s/g, ""),
                });
                setWant(null);
                reload();
              });
            }}
          >
            <h3 style={{ color: "var(--loss)", margin: 0 }}>Переход на реальные деньги</h3>
            <p style={{ fontSize: 14, margin: 0 }}>
              Баланс реального счёта: <span className="mono">{money(a.keys.real.equity_usd)}</span>. Если идёт
              торговля, движок сначала закроет позиции на демо и только потом начнёт на реальном.
            </p>
            <label>
              Лимит депозита — сколько отдать стратегии, USD
              <input name="capital_usd" type="number" min={50} step={50} required defaultValue={100} />
            </label>
            <label>
              Дневной лимит убытка, % от лимита депозита
              <input name="daily_loss_pct" type="number" min={0.5} max={20} step={0.5} required defaultValue={2} />
            </label>
            <label style={{ display: "flex", gap: 8, alignItems: "flex-start", color: "var(--text)" }}>
              <input type="checkbox" name="confirm" style={{ marginTop: 4 }} />
              <span>
                Понимаю: деньги настоящие, можно потерять весь лимит депозита; прибыль не гарантирована; результаты
                на истории и на демо не обещают будущих.
              </span>
            </label>
            <label>
              Свежий код 2FA
              <input className="code-input" name="code" inputMode="numeric" autoComplete="one-time-code" pattern="\d{6}" maxLength={6} required />
            </label>
            {error ? <p className="err">{error}</p> : null}
            <button className="btn" disabled={busy} style={{ background: "var(--loss)", color: "#fff" }}>
              Перейти на реальный счёт
            </button>
          </form>
        )
      ) : null}
    </div>
  );
}

function AccountCard({ a, ip, realAllowed, reload }: { a: Account; ip: string; realAllowed: boolean; reload: () => void }) {
  const { busy, error, run } = useSubmit();
  return (
    <div className="card" style={{ display: "grid", gap: 8 }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
        <h3 style={{ margin: 0 }}>{a.name}</h3>
        <span className="pill" style={a.mode === "real" ? { borderColor: "var(--loss)", color: "var(--loss)" } : undefined}>
          {a.mode === "demo" ? "демо" : "реальный счёт"}
        </span>
      </div>
      <div style={{ fontSize: 14, display: "grid", gap: 4 }}>
        <div>
          {a.stopped ? (
            <span style={{ color: "var(--loss)" }}>■ Остановлен вручную</span>
          ) : a.status === "ok" ? (
            <span style={{ color: "var(--gain)" }}>✓ Ключ в порядке</span>
          ) : (
            <span style={{ color: "var(--loss)" }}>✗ {a.status_detail}</span>
          )}
        </div>
        <div className="muted">
          Ключ <span className="mono">••••{a.key_tail}</span> · IP {a.ips.join(", ") || "—"}
        </div>
        <div>
          Баланс: <span className="mono">{money(a.equity_usd)}</span>
        </div>
        {a.checked_at ? (
          <div className="muted" style={{ fontSize: 12 }}>
            проверен {new Date(a.checked_at).toLocaleString("ru-RU")}
          </div>
        ) : null}
        {a.warnings.map((w) => (
          <div key={w} style={{ color: "var(--accent)", fontSize: 13 }}>
            ⚠ {w}
          </div>
        ))}
      </div>
      <ModeSwitch a={a} ip={ip} realAllowed={realAllowed} reload={reload} />
      <TradingSettings a={a} reload={reload} />
      <EnginePanel a={a} />
      {error ? <p className="err">{error}</p> : null}
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <button className="btn ghost" disabled={busy} onClick={() => run(async () => { await api(`/accounts/${a.id}/recheck`, {}); reload(); })}>
          Перепроверить
        </button>
        <button
          className="btn ghost"
          disabled={busy}
          onClick={() => run(async () => { await api(`/accounts/${a.id}/stop`, { stopped: !a.stopped }); reload(); })}
        >
          {a.stopped ? "Снять аварийную остановку" : "Аварийная остановка"}
        </button>
        <button
          className="btn ghost"
          disabled={busy}
          style={{ color: "var(--loss)" }}
          onClick={() => {
            if (!confirm(`Удалить кабинет «${a.name}»? Ключ будет стёрт.`)) return;
            run(async () => {
              const r = await fetch(`/api/accounts/${a.id}`, { method: "DELETE", credentials: "same-origin" });
              if (!r.ok) throw new ApiError(r.status, "Не удалось удалить");
              reload();
            });
          }}
        >
          Удалить
        </button>
      </div>
    </div>
  );
}

export default function AccountsPage() {
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);
  const [ip, setIp] = useState("");
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [adding, setAdding] = useState(false);
  const [realAllowed, setRealAllowed] = useState(false);

  const load = useCallback(async () => {
    try {
      const m = await api<Me>("/auth/me");
      if (m.totp_enabled && !m.mfa_passed) return router.replace("/account");
      setMe(m);
      const [list, status] = await Promise.all([
        api<Account[]>("/accounts"),
        api<{ server_ip: string; real_trading_allowed: boolean }>("/status"),
      ]);
      setAccounts(list);
      setIp(status.server_ip);
      setRealAllowed(status.real_trading_allowed);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) router.replace("/login");
    }
  }, [router]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- загрузка данных при открытии
    load();
  }, [load]);

  return (
    <main className="wrap">
      <Header />
      <h1 style={{ fontSize: 28 }}>Кабинеты Bybit</h1>
      <RiskNote />
      {!me ? (
        <p className="muted">Загрузка…</p>
      ) : !me.totp_enabled ? (
        <div className="card" style={{ maxWidth: 520 }}>
          <h3>Сначала включите 2FA</h3>
          <p className="muted" style={{ fontSize: 14 }}>
            Подключать ключи биржи можно только с двухфакторной защитой аккаунта.
          </p>
          <Link href="/account">Включить 2FA →</Link>
        </div>
      ) : (
        <>
          {accounts.length ? (
            <div className="grid" style={{ marginBottom: 24 }}>
              {accounts.map((a) => (
                <AccountCard key={a.id} a={a} ip={ip} realAllowed={realAllowed} reload={load} />
              ))}
            </div>
          ) : (
            <p className="muted">Кабинетов пока нет.</p>
          )}
          <Signals />
          {adding ? (
            <AddWizard
              ip={ip}
              onDone={() => {
                setAdding(false);
                load();
              }}
            />
          ) : (
            <button className="btn" onClick={() => setAdding(true)}>
              Добавить кабинет
            </button>
          )}
        </>
      )}
      <Footer />
    </main>
  );
}
