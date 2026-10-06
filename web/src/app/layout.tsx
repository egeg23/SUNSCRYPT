import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "SUNSCRYPT",
  description: "Автоматическая торговля криптовалютными перпетуалами на Bybit",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ru">
      <body>{children}</body>
    </html>
  );
}
