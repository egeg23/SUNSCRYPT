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
};

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

function AddWizard({ ip, onDone }: { ip: string; onDone: () => void }) {
  const [mode, setMode] = useState<"demo" | "real" | null>(null);
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
        <button className="btn ghost" style={{ padding: "4px 10px", fontSize: 13 }} onClick={() => setMode(null)}>
          ← другой счёт
        </button>
      </div>
      <Steps mode={mode} ip={ip} />
      <form
        className="form"
        style={{ maxWidth: 480 }}
        onSubmit={(e) => {
          e.preventDefault();
          const f = new FormData(e.currentTarget);
          setResult(null);
          run(async () => {
            try {
              await api("/accounts", {
                name: String(f.get("name") || (mode === "demo" ? "Демо" : "Реальный")),
                mode,
                api_key: String(f.get("api_key")).trim(),
                api_secret: String(f.get("api_secret")).trim(),
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
        <label>
          Название кабинета
          <input name="name" maxLength={60} placeholder={mode === "demo" ? "Демо" : "Основной"} />
        </label>
        <label>
          API Key
          <input name="api_key" autoComplete="off" spellCheck={false} required />
        </label>
        <label>
          API Secret
          <input name="api_secret" type="password" autoComplete="off" spellCheck={false} required />
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

function AccountCard({ a, reload }: { a: Account; reload: () => void }) {
  const { busy, error, run } = useSubmit();
  return (
    <div className="card" style={{ display: "grid", gap: 8 }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
        <h3 style={{ margin: 0 }}>{a.name}</h3>
        <span className="pill">{a.mode === "demo" ? "демо" : "реальный"}</span>
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
          {a.stopped ? "Возобновить" : "Остановить"}
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

  const load = useCallback(async () => {
    try {
      const m = await api<Me>("/auth/me");
      if (m.totp_enabled && !m.mfa_passed) return router.replace("/account");
      setMe(m);
      const [list, status] = await Promise.all([
        api<Account[]>("/accounts"),
        api<{ server_ip: string }>("/status"),
      ]);
      setAccounts(list);
      setIp(status.server_ip);
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
                <AccountCard key={a.id} a={a} reload={load} />
              ))}
            </div>
          ) : (
            <p className="muted">Кабинетов пока нет.</p>
          )}
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
