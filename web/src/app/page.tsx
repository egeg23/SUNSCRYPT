import Link from "next/link";
import { Footer } from "@/components/Footer";
import { Header } from "@/components/Header";
import { RiskNote } from "@/components/RiskNote";
import { StackStatus } from "@/components/StackStatus";

export default function Home() {
  return (
    <main className="wrap">
      <Header />
      <h1>Автоматическая торговля перпетуалами на Bybit</h1>
      <p className="muted" style={{ maxWidth: 680, fontSize: 18 }}>
        Сигнал модели Kronos → исполнение NautilusTrader → ваш кабинет Bybit. Дашборд в
        реальном времени и Telegram-бот. Сервис в разработке.
      </p>
      <RiskNote />
      <div className="grid">
        <StackStatus />
        <div className="card">
          <h3>Что дальше</h3>
          <p className="muted" style={{ fontSize: 14 }}>
            Вход с 2FA работает; доступ — по приглашению владельца. Дальше — подключение кабинета Bybit по API-ключу без права вывода,
            дашборд с честной статистикой после комиссий.
          </p>
          <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
            <Link href="/login">Вход →</Link>
            <Link href="/brand">Бренд →</Link>
          </div>
        </div>
      </div>
      <Footer />
    </main>
  );
}
