import type { Metadata } from "next";
// Self-hosted fonts (no build-time or runtime requests to Google): Unbounded, Golos Text, JetBrains Mono.
import "@fontsource-variable/unbounded";
import "@fontsource-variable/golos-text";
import "@fontsource-variable/jetbrains-mono";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "SUNSCRYPT", template: "%s · SUNSCRYPT" },
  description: "Автоматическая торговля криптовалютными перпетуалами Bybit с прозрачной статистикой",
  icons: { apple: "/brand/apple-touch-icon.png" },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ru">
      <body>{children}</body>
    </html>
  );
}
