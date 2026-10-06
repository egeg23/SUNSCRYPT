import type { Metadata } from "next";
import { body, display, mono } from "./fonts";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "SUNSCRYPT", template: "%s · SUNSCRYPT" },
  description: "Автоматическая торговля криптовалютными перпетуалами Bybit с прозрачной статистикой",
  icons: { apple: "/brand/apple-touch-icon.png" },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ru" className={`${display.variable} ${body.variable} ${mono.variable}`}>
      <body>{children}</body>
    </html>
  );
}
