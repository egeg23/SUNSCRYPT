import Link from "next/link";

export function Header() {
  return (
    <header className="top">
      <Link href="/" aria-label="SUNSCRYPT — на главную">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img className="logo logo-light" src="/brand/logo-light.svg" alt="SUNSCRYPT" />
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img className="logo logo-dark" src="/brand/logo-dark.svg" alt="SUNSCRYPT" />
      </Link>
      <nav>
        <Link href="/brand">Бренд</Link>
        <Link href="/accounts">Bybit</Link>
        <Link href="/account">Профиль</Link>
      </nav>
    </header>
  );
}
