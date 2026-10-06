import { Logo } from "@/components/Logo";
import { ServiceStatus } from "@/components/ServiceStatus";

export default function Home() {
  return (
    <main style={{ maxWidth: 720, margin: "0 auto", padding: "40px 16px 64px", display: "grid", gap: 28 }}>
      <Logo height={32} />
      <h1 style={{ fontSize: "clamp(28px, 5vw, 44px)", fontWeight: 700 }}>
        Торговый робот для Bybit с честной статистикой
      </h1>
      <p style={{ color: "var(--muted)", maxWidth: "60ch", margin: 0 }}>
        Подключите кабинет по API, начните на демо-счёте и смотрите рост баланса и долю успешных сделок в
        реальном времени. Прибыль не гарантирована: мы показываем результаты как есть.
      </p>
      <ServiceStatus />
    </main>
  );
}
