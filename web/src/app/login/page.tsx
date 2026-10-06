"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { AuthShell } from "@/components/AuthShell";
import { api } from "@/lib/api";
import { useSubmit } from "@/lib/useForm";

export default function LoginPage() {
  const router = useRouter();
  const { busy, error, run } = useSubmit();
  const [step, setStep] = useState<"password" | "code">("password");
  const [email, setEmail] = useState("");

  return (
    <AuthShell title={step === "password" ? "Вход" : "Код 2FA"}>
      {step === "password" ? (
        <form
          className="form"
          onSubmit={(e) => {
            e.preventDefault();
            const f = new FormData(e.currentTarget);
            run(async () => {
              const r = await api<{ mfa_required: boolean }>("/auth/login", {
                email: f.get("email"),
                password: f.get("password"),
              });
              if (r.mfa_required) setStep("code");
              else router.push("/account");
            });
          }}
        >
          <label>
            Почта
            <input
              name="email"
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </label>
          <label>
            Пароль
            <input name="password" type="password" autoComplete="current-password" required />
          </label>
          {error ? <p className="err">{error}</p> : null}
          {error?.startsWith("Подтвердите почту") ? (
            <button
              type="button"
              className="btn ghost"
              onClick={() => run(async () => void (await api("/auth/verify/resend", { email })))}
            >
              Отправить письмо ещё раз
            </button>
          ) : null}
          <button className="btn" disabled={busy}>
            Войти
          </button>
        </form>
      ) : (
        <form
          className="form"
          onSubmit={(e) => {
            e.preventDefault();
            const f = new FormData(e.currentTarget);
            run(async () => {
              await api("/auth/2fa/verify", { code: String(f.get("code")).replace(/\s/g, "") });
              router.push("/account");
            });
          }}
        >
          <label>
            6 цифр из приложения (Google Authenticator и т. п.)
            <input
              className="code-input"
              name="code"
              inputMode="numeric"
              autoComplete="one-time-code"
              pattern="\d{6}"
              maxLength={6}
              required
              autoFocus
            />
          </label>
          {error ? <p className="err">{error}</p> : null}
          <button className="btn" disabled={busy}>
            Подтвердить
          </button>
        </form>
      )}
      <div className="links">
        <span className="muted">Доступ — по приглашению владельца</span>
        <span className="muted">Забыли пароль? Попросите у владельца ссылку сброса</span>
      </div>
    </AuthShell>
  );
}
