"use client";

import { useEffect, useState } from "react";

type Health = { status: string; db: boolean; redis: boolean; version: string };

export function ServiceStatus() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    fetch("/api/health")
      .then((r) => r.json())
      .then(setHealth)
      .catch(() => setError(true));
  }, []);

  if (error) return <p data-testid="status" className="num" style={{ color: "var(--muted)", fontSize: 14, margin: 0 }}>API недоступен</p>;
  if (!health) return <p data-testid="status" className="num" style={{ color: "var(--muted)", fontSize: 14, margin: 0 }}>Проверяю сервис…</p>;
  return (
    <p data-testid="status" className="num" style={{ color: "var(--muted)", fontSize: 14, margin: 0 }}>
      API {health.version}: {health.status === "ok" ? "работает" : "частично доступен"} · БД{" "}
      {health.db ? "✓" : "✗"} · Redis {health.redis ? "✓" : "✗"}
    </p>
  );
}
