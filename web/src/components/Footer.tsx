import Link from "next/link";

export function Footer() {
  return (
    <footer>
      SUNSCRYPT · сервис в разработке · торговля только на демо-счёте · прибыль не
      гарантирована · <Link href="/terms">условия и риски</Link>
    </footer>
  );
}
