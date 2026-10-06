"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { AuthShell } from "@/components/AuthShell";
import { ApiError, api } from "@/lib/api";
import { tokenFromUrl } from "@/lib/useForm";

export default function VerifyPage() {
  const [state, setState] = useState<"wait" | "ok" | string>("wait");

  useEffect(() => {
    api("/auth/verify", { token: tokenFromUrl() })
      .then(() => setState("ok"))
      .catch((e) => setState(e instanceof ApiError ? e.message : "Нет связи с сервером"));
  }, []);

  return (
    <AuthShell title="Подтверждение почты">
      {state === "wait" ? <p className="muted">Проверяю ссылку…</p> : null}
      {state === "ok" ? (
        <>
          <p className="ok">Почта подтверждена.</p>
          <div className="links">
            <Link href="/login">Войти →</Link>
          </div>
        </>
      ) : null}
      {state !== "wait" && state !== "ok" ? <p className="err">{state}</p> : null}
    </AuthShell>
  );
}
