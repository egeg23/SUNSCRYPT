"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { AuthShell } from "@/components/AuthShell";
import { api } from "@/lib/api";
import { TERMS_VERSION } from "@/lib/terms";
import { tokenFromUrl, useSubmit } from "@/lib/useForm";

// Доступ закрытый: аккаунт создаётся только по ссылке-приглашению от владельца.
export default function InvitePage() {
  const router = useRouter();
  const { busy, error, run } = useSubmit();
  const [agree, setAgree] = useState(false);

  return (
    <AuthShell title="Приглашение в SUNSCRYPT">
      <form
        className="form"
        onSubmit={(e) => {
          e.preventDefault();
          const f = new FormData(e.currentTarget);
          run(async () => {
            await api("/auth/register", {
              invite: tokenFromUrl(),
              email: f.get("email"),
              password: f.get("password"),
              terms: TERMS_VERSION,
            });
            router.push("/account");
          });
        }}
      >
        <label>
          Почта — будет логином
          <input name="email" type="email" autoComplete="email" required />
        </label>
        <label>
          Пароль — не короче 10 символов
          <input name="password" type="password" autoComplete="new-password" minLength={10} required />
        </label>
        <label style={{ display: "flex", gap: 8, alignItems: "flex-start", color: "var(--text)" }}>
          <input
            type="checkbox"
            checked={agree}
            onChange={(e) => setAgree(e.target.checked)}
            style={{ marginTop: 4 }}
          />
          <span>
            Прочитал(а) и принимаю{" "}
            <Link href="/terms" target="_blank">
              условия и риски
            </Link>
            : торговля деривативами — высокий риск, прибыль не гарантирована.
          </span>
        </label>
        {error ? <p className="err">{error}</p> : null}
        <button className="btn" disabled={busy || !agree}>
          Создать аккаунт
        </button>
      </form>
      <div className="links">
        <Link href="/login">Уже есть аккаунт — войти</Link>
      </div>
    </AuthShell>
  );
}
