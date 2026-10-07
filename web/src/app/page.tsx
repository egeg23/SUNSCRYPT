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
        Стратегии, отобранные на истории после комиссий → исполнение NautilusTrader → ваш кабинет
        Bybit. Дашборд в реальном времени. Сервис в разработке, торговля — только на демо-счёте.
      </p>
      <RiskNote />
      <div className="grid">
        <StackStatus />
        <div className="card">
          <h3>Что дальше</h3>
          <p className="muted" style={{ fontSize: 14 }}>
            Доступ — по приглашению владельца, вход с 2FA. Кабинет Bybit подключается API-ключом без права
            вывода; на дашборде — честная статистика после комиссий и фандинга.
          </p>
          <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
            <Link href="/login">Вход →</Link>
            <Link href="/terms">Условия и риски →</Link>
          </div>
        </div>
      </div>
      <Footer />
    </main>
  );
}
