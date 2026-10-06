"use client";

import Link from "next/link";
import { useState } from "react";
import { AuthShell } from "@/components/AuthShell";
import { api } from "@/lib/api";
import { tokenFromUrl, useSubmit } from "@/lib/useForm";

export default function ResetPage() {
  const { busy, error, run, setError } = useSubmit();
  const [done, setDone] = useState(false);
  return (
    <AuthShell title="Новый пароль">
      {done ? (
        <>
          <p className="ok">Пароль изменён. Все прежние входы закрыты.</p>
          <div className="links">
            <Link href="/login">Войти →</Link>
          </div>
        </>
      ) : (
        <form
          className="form"
          onSubmit={(e) => {
            e.preventDefault();
            const f = new FormData(e.currentTarget);
            if (f.get("password") !== f.get("password2")) {
              setError("Пароли не совпадают");
              return;
            }
            run(async () => {
              await api("/auth/password/reset", { token: tokenFromUrl(), password: f.get("password") });
              setDone(true);
            });
          }}
        >
          <label>
            Новый пароль — не короче 10 символов
            <input name="password" type="password" autoComplete="new-password" minLength={10} required />
          </label>
          <label>
            Ещё раз
            <input name="password2" type="password" autoComplete="new-password" minLength={10} required />
          </label>
          {error ? <p className="err">{error}</p> : null}
          <button className="btn" disabled={busy}>
            Сохранить
          </button>
        </form>
      )}
    </AuthShell>
  );
}
