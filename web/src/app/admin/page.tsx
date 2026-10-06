"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { Footer } from "@/components/Footer";
import { Header } from "@/components/Header";
import { ApiError, api } from "@/lib/api";
import { useSubmit } from "@/lib/useForm";

type InviteRow = { note: string | null; created_at: string; status: string; used_by: string | null };
type UserRow = { id: string; email: string; is_admin: boolean; totp_enabled: boolean; created_at: string };

const STATUS: Record<string, string> = {
  active: "ждёт",
  used: "использовано",
  expired: "истекло",
};

function CopyLink({ link, hint }: { link: string; hint: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="card" style={{ marginTop: 12 }}>
      <p style={{ fontSize: 14, margin: "0 0 8px" }}>{hint}</p>
      <code style={{ wordBreak: "break-all", fontSize: 13 }}>{link}</code>
      <div style={{ marginTop: 10 }}>
        <button
          className="btn ghost"
          onClick={async () => {
            await navigator.clipboard.writeText(link);
            setCopied(true);
          }}
        >
          {copied ? "Скопировано" : "Скопировать"}
        </button>
      </div>
    </div>
  );
}

export default function AdminPage() {
  const router = useRouter();
  const { busy, error, run, setError } = useSubmit();
  const [invites, setInvites] = useState<InviteRow[]>([]);
  const [users, setUsers] = useState<UserRow[]>([]);
  const [link, setLink] = useState<{ url: string; hint: string } | null>(null);
  const [flags, setFlags] = useState<Record<string, boolean>>({});

  const load = useCallback(async () => {
    try {
      const [i, u] = await Promise.all([
        api<InviteRow[]>("/admin/invites"),
        api<UserRow[]>("/admin/users"),
      ]);
      setInvites(i);
      setUsers(u);
      setFlags(await api<Record<string, boolean>>("/admin/flags"));
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) router.replace("/login");
      else if (e instanceof ApiError) setError(e.message);
    }
  }, [router, setError]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- загрузка данных при открытии
    load();
  }, [load]);

  return (
    <main className="wrap">
      <Header />
      <h1 style={{ fontSize: 28 }}>Владелец</h1>
      {error ? <p className="err">{error}</p> : null}

      <section>
        <h2>Аварийная остановка</h2>
        <div className="card" style={{ maxWidth: 560 }}>
          {flags.global_stop ? (
            <p className="err" style={{ marginBottom: 12 }}>
              Включена: все кабинеты закрыли позиции и не торгуют.
            </p>
          ) : (
            <p className="muted" style={{ fontSize: 14 }}>
              Одна кнопка для всех кабинетов: движок отменяет ордера и закрывает позиции. Реальная
              торговля: <b>{flags.real_trading_enabled ? "включена" : "выключена"}</b>.
            </p>
          )}
          <button
            className="btn"
            disabled={busy}
            style={flags.global_stop ? undefined : { background: "var(--loss)", color: "#fff" }}
            onClick={() => {
              if (!flags.global_stop && !confirm("Остановить торговлю во всех кабинетах и закрыть позиции?")) return;
              run(async () => {
                setFlags(await api<Record<string, boolean>>("/admin/global-stop", { stopped: !flags.global_stop }));
              });
            }}
          >
            {flags.global_stop ? "Снять общую остановку" : "Остановить всё"}
          </button>
        </div>
      </section>

      <section>
        <h2>Пригласить</h2>
        <p className="muted" style={{ fontSize: 14, maxWidth: 640 }}>
          Доступ только по приглашению. Ссылка одноразовая, действует 7 дней. Отправьте её
          человеку сами — например, в Telegram.
        </p>
        <form
          className="form"
          style={{ maxWidth: 420 }}
          onSubmit={(e) => {
            e.preventDefault();
            const f = new FormData(e.currentTarget);
            run(async () => {
              const r = await api<{ link: string }>("/admin/invites", { note: f.get("note") || null });
              setLink({ url: r.link, hint: "Ссылка-приглашение:" });
              e.currentTarget?.reset();
              await load();
            });
          }}
        >
          <label>
            Для кого (заметка, по желанию)
            <input name="note" maxLength={120} />
          </label>
          <button className="btn" disabled={busy}>
            Создать приглашение
          </button>
        </form>
        {link ? <CopyLink link={link.url} hint={link.hint} /> : null}
      </section>

      <section>
        <h2>Пользователи</h2>
        <div className="table-wrap">
          <table className="log">
            <thead>
              <tr>
                <th>Почта</th>
                <th>2FA</th>
                <th>С нами с</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id}>
                  <td>
                    {u.email}
                    {u.is_admin ? " · владелец" : ""}
                  </td>
                  <td style={{ color: u.totp_enabled ? "var(--gain)" : "var(--muted)" }}>
                    {u.totp_enabled ? "✓ включена" : "нет"}
                  </td>
                  <td className="mono">{new Date(u.created_at).toLocaleDateString("ru-RU")}</td>
                  <td>
                    <button
                      className="btn ghost"
                      style={{ padding: "6px 10px", fontSize: 13 }}
                      onClick={() =>
                        run(async () => {
                          const r = await api<{ link: string }>(`/admin/users/${u.id}/reset-link`, {});
                          setLink({ url: r.link, hint: `Ссылка сброса пароля для ${u.email} (1 час):` });
                        })
                      }
                    >
                      Ссылка сброса пароля
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section>
        <h2>Приглашения</h2>
        <div className="table-wrap">
          <table className="log">
            <thead>
              <tr>
                <th>Создано</th>
                <th>Для кого</th>
                <th>Статус</th>
                <th>Кто зарегистрировался</th>
              </tr>
            </thead>
            <tbody>
              {invites.map((i, n) => (
                <tr key={n}>
                  <td className="mono">{new Date(i.created_at).toLocaleString("ru-RU")}</td>
                  <td>{i.note ?? "—"}</td>
                  <td>{STATUS[i.status] ?? i.status}</td>
                  <td>{i.used_by ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      <Footer />
    </main>
  );
}
