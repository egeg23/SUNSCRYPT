import { ServiceStatus } from "@/components/ServiceStatus";

export default function Home() {
  return (
    <main style={{ maxWidth: 640, margin: "0 auto", padding: "64px 16px" }}>
      <h1 style={{ letterSpacing: "0.04em" }}>SUNSCRYPT</h1>
      <p style={{ color: "var(--muted)" }}>Сервис в разработке. Этап 0: каркас.</p>
      <ServiceStatus />
    </main>
  );
}
