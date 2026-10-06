import type { Metadata, Viewport } from "next";
import "@fontsource-variable/unbounded";
import "@fontsource-variable/manrope";
import "@fontsource-variable/jetbrains-mono";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "SUNSCRYPT", template: "%s · SUNSCRYPT" },
  description:
    "Автоматическая торговля перпетуалами на Bybit. Сейчас — только демо-счёт. Прибыль не гарантирована.",
  // До запуска сайт закрыт от поиска.
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: dark)", color: "#0B0D10" },
    { media: "(prefers-color-scheme: light)", color: "#FAF7F0" },
  ],
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="ru">
      <body>{children}</body>
    </html>
  );
}
