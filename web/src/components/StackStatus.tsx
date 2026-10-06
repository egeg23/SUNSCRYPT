"use client";

import { useEffect, useState } from "react";

type Health = { status: string; db: boolean; redis: boolean; commit: string };
type Status = {
  default_mode: string;
  real_trading_allowed: boolean;
  global_stop: boolean;
  max_leverage: number;
  default_leverage: number;
};

async function getJson<T>(url: string): Promise<T | null> {
  try {
    const r = await fetch(url, { cache: "no-store" });
    return (await r.json()) as T;
  } catch {
    return null;
  }
}

function Item({ ok, label }: { ok: boolean | undefined; label: string }) {
  const cls = ok === undefined ? "dot" : ok ? "dot ok" : "dot bad";
  return (
    <span className="pill">
      <span className={cls} aria-hidden />
      {label}
    </span>
  );
}

/** Живое состояние стека: API, база, Redis и режим торговли. */
export function StackStatus() {
  const [health, setHealth] = useState<Health | null | undefined>(undefined);
  const [status, setStatus] = useState<Status | null | undefined>(undefined);

  useEffect(() => {
    const load = async () => {
      const [h, s] = await Promise.all([
        getJson<Health>("/api/health"),
        getJson<Status>("/api/status"),
      ]);
      setHealth(h);
      setStatus(s);
    };
    load();
    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, []);

  const loading = health === undefined;
  return (
    <div className="card">
      <h3>Состояние сервиса</h3>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, margin: "12px 0" }}>
        <Item ok={loading ? undefined : !!health} label="API" />
        <Item ok={loading ? undefined : health?.db} label="База данных" />
        <Item ok={loading ? undefined : health?.redis} label="Redis" />
      </div>
      {status ? (
        <p className="muted" style={{ fontSize: 14 }}>
          Режим по умолчанию: <b>{status.default_mode === "demo" ? "демо" : "реальный"}</b>.
          Реальная торговля: <b>{status.real_trading_allowed ? "разрешена" : "выключена"}</b>.
          Плечо: <span className="mono">{status.default_leverage}×</span> по умолчанию, не выше{" "}
          <span className="mono">{status.max_leverage}×</span>.
          {status.global_stop ? " Включена аварийная остановка." : ""}
        </p>
      ) : (
        <p className="muted" style={{ fontSize: 14 }}>
          {loading ? "Проверяю…" : "API не отвечает."}
        </p>
      )}
      {health?.commit ? (
        <p className="muted mono" style={{ fontSize: 12, margin: 0 }}>
          версия {health.commit}
        </p>
      ) : null}
    </div>
  );
}
