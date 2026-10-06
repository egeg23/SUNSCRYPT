import { Footer } from "@/components/Footer";
import { Header } from "@/components/Header";

export function AuthShell({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <main className="wrap">
      <Header />
      <div className="auth">
        <h1 style={{ fontSize: 28 }}>{title}</h1>
        <div className="card">{children}</div>
      </div>
      <Footer />
    </main>
  );
}
