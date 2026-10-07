"use client";

import QRCode from "qrcode";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { Footer } from "@/components/Footer";
import { Header } from "@/components/Header";
import { RiskNote } from "@/components/RiskNote";
import { ApiError, api, type Me } from "@/lib/api";
import { useSubmit } from "@/lib/useForm";

type LoginRow = {
  at: string;
  event: string;
  success: boolean;
  reason: string | null;
  ip: string | null;
  user_agent: string | null;
};

const EVENTS: Record<string, string> = {
  login: "Вход по паролю",
  "2fa": "Код 2FA",
  register: "Регистрация",
  "2fa_enabled": "2FA включена",
  reset_requested: "Запрос сброса пароля",
  password_reset: "Пароль изменён",
};

const REASONS: Record<string, string> = {
  bad_password: "неверный пароль",
  bad_code: "неверный код",
  email_not_verified: "почта не подтверждена",
};

function CodeForm({ action, label, onDone }: { action: string; label: string; onDone: () => void }) {
  const { busy, error, run } = useSubmit();
  return (
    <form
      className="form"
      onSubmit={(e) => {
        e.preventDefault();
        const f = new FormData(e.currentTarget);
        run(async () => {
          await api(action, { code: String(f.get("code")).replace(/\s/g, "") });
          onDone();
        });
      }}
    >
      <label>
        6 цифр из приложения
        <input
          className="code-input"
          name="code"
          inputMode="numeric"
          autoComplete="one-time-code"
          pattern="\d{6}"
          maxLength={6}
          required
        />
      </label>
      {error ? <p className="err">{error}</p> : null}
      <button className="btn" disabled={busy}>
        {label}
      </button>
    </form>
  );
}

function TwoFactorSetup({ onDone }: { onDone: () => void }) {
  const { busy, error, run } = useSubmit();
  const [setup, setSetup] = useState<{ secret: string; qr: string } | null>(null);

  if (!setup) {
    return (
      <>
        <p className="muted" style={{ fontSize: 14 }}>
          2FA обязательна перед подключением ключей Bybit. Понадобится приложение-генератор
          кодов: Google Authenticator, Яндекс Ключ, 1Password и т. п.
        </p>
        {error ? <p className="err">{error}</p> : null}
        <button
          className="btn"
          disabled={busy}
          onClick={() =>
            run(async () => {
              const r = await api<{ secret: string; otpauth_uri: string }>("/auth/2fa/setup", {});
              const qr = await QRCode.toDataURL(r.otpauth_uri, { margin: 1, width: 220 });
              setSetup({ secret: r.secret, qr });
            })
          }
        >
          Включить 2FA
        </button>
      </>
    );
  }
  return (
    <div style={{ display: "grid", gap: 14 }}>
      <p style={{ fontSize: 14, margin: 0 }}>
        1. Отсканируйте QR-код приложением. Или введите ключ вручную:
      </p>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={setup.qr} alt="QR-код для приложения 2FA" width={220} height={220} style={{ borderRadius: 8, background: "#fff" }} />
      <code style={{ wordBreak: "break-all", fontSize: 14 }}>{setup.secret}</code>
      <p style={{ fontSize: 14, margin: 0 }}>2. Введите код, который показало приложение:</p>
      <CodeForm action="/auth/2fa/enable" label="Подтвердить и включить" onDone={onDone} />
    </div>
  );
}

function TelegramCard({ me, onChange }: { me: Me; onChange: () => void }) {
  const [link, setLink] = useState<{ code: string; link: string } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  return (
    <div className="card">
      <h3>Telegram</h3>
      {me.telegram_linked ? (
        <>
          <p className="ok">Бот @SUNSCRYPT_tradebot привязан: сделки, тревоги, дневной отчёт.</p>
          <p className="muted" style={{ fontSize: 14 }}>
            Команды: /status, /report, /stop — аварийная остановка ваших кабинетов.
          </p>
          <button
            className="btn ghost"
            onClick={async () => {
              await api("/auth/telegram", undefined, "DELETE");
              onChange();
            }}
          >
            Отвязать
          </button>
        </>
      ) : !me.totp_enabled ? (
        <p className="muted" style={{ fontSize: 14 }}>
          Бот умеет останавливать торговлю — сначала включите 2FA.
        </p>
      ) : link ? (
        <>
          <p style={{ fontSize: 14 }}>
            Откройте ссылку в Telegram и нажмите «Запустить» — или отправьте боту{" "}
            <code>/start {link.code}</code>. Код действует 10 минут.
          </p>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <a className="btn" href={link.link} target="_blank" rel="noreferrer">
              Открыть Telegram
            </a>
            <button className="btn ghost" onClick={onChange}>
              Я привязал — обновить
            </button>
          </div>
        </>
      ) : (
        <>
          <p className="muted" style={{ fontSize: 14 }}>
            Уведомления о каждой сделке, тревоги, дневной отчёт и аварийная остановка из чата.
          </p>
          <button
            className="btn"
            onClick={async () => {
              try {
                setLink(await api<{ code: string; link: string }>("/auth/telegram/link", {}));
                setErr(null);
              } catch (e) {
                setErr(e instanceof ApiError ? e.message : "Не получилось");
              }
            }}
          >
            Привязать Telegram
          </button>
        </>
      )}
      {err ? <p className="err">{err}</p> : null}
    </div>
  );
}

export default function AccountPage() {
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);
  const [logins, setLogins] = useState<LoginRow[]>([]);

  const load = useCallback(async () => {
    try {
      const m = await api<Me>("/auth/me");
      setMe(m);
      if (!m.totp_enabled || m.mfa_passed) setLogins(await api<LoginRow[]>("/auth/logins"));
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) router.replace("/login");
    }
  }, [router]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- загрузка данных при открытии
    load();
  }, [load]);

  if (!me) {
    return (
      <main className="wrap">
        <Header />
        <p className="muted">Загрузка…</p>
      </main>
    );
  }

  const locked = me.totp_enabled && !me.mfa_passed;

  return (
    <main className="wrap">
      <Header />
      <div style={{ display: "flex", justifyContent: "space-between", gap: 16, flexWrap: "wrap", alignItems: "baseline" }}>
        <h1 style={{ fontSize: 28 }}>Личный кабинет</h1>
        <button
          className="btn ghost"
          onClick={async () => {
            await api("/auth/logout", {});
            router.replace("/login");
          }}
        >
          Выйти
        </button>
      </div>
      <p className="muted">
        {me.email}
        {me.is_admin && !locked ? (
          <>
            {" · "}
            <a href="/admin">раздел владельца →</a>
          </>
        ) : null}
      </p>

      {locked ? (
        <div className="card" style={{ maxWidth: 420 }}>
          <h3>Введите код 2FA</h3>
          <CodeForm action="/auth/2fa/verify" label="Подтвердить" onDone={load} />
        </div>
      ) : (
        <>
          <RiskNote />
          <div className="grid">
            <div className="card">
              <h3>Двухфакторная защита (2FA)</h3>
              {me.totp_enabled ? (
                <p className="ok">Включена. При входе понадобится код из приложения.</p>
              ) : (
                <TwoFactorSetup onDone={load} />
              )}
            </div>
            <div className="card">
              <h3>Кабинеты Bybit</h3>
              <p className="muted" style={{ fontSize: 14 }}>
                Подключение по API-ключу без права вывода, с привязкой к IP сервера.
                {me.totp_enabled ? "" : " Сначала включите 2FA."}
              </p>
              <a href="/accounts">Перейти к кабинетам →</a>
            </div>
            <TelegramCard me={me} onChange={load} />
          </div>

          <section>
            <h2>Журнал входов</h2>
            <div className="table-wrap">
              <table className="log">
                <thead>
                  <tr>
                    <th>Когда</th>
                    <th>Что</th>
                    <th>Итог</th>
                    <th>IP</th>
                    <th>Устройство</th>
                  </tr>
                </thead>
                <tbody>
                  {logins.map((l, i) => (
                    <tr key={i}>
                      <td className="mono">{new Date(l.at).toLocaleString("ru-RU")}</td>
                      <td>{EVENTS[l.event] ?? l.event}</td>
                      <td style={{ color: l.success ? "var(--gain)" : "var(--loss)" }}>
                        {l.success ? "✓ успешно" : `✗ ${REASONS[l.reason ?? ""] ?? "отказ"}`}
                      </td>
                      <td className="mono">{l.ip ?? "—"}</td>
                      <td className="muted">{l.user_agent?.slice(0, 60) ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
      <Footer />
    </main>
  );
}
