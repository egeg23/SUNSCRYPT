"""Проверка демо-ключа владельца нашим же кодом — шаг выкатки на сервере.

Ключ и секрет читаются из stdin (две строки), чтобы не светиться в списке
процессов; в вывод попадают только права, IP и баланс."""

import asyncio
import sys

from app import bybit


async def main() -> None:
    key, secret = (sys.stdin.readline().strip(), sys.stdin.readline().strip())
    try:
        chk = await bybit.check_key("demo", key, secret)
    except bybit.BybitError as e:
        print(f"▸ Проверка ключа сервисом: отклонён — {e}")
        return
    verdict = "принят" if chk.ok else "отклонён"
    print(f"▸ Проверка ключа сервисом: {verdict}")
    for p in chk.problems:
        print(f"  ✗ {p}")
    for w in chk.warnings:
        print(f"  ⚠ {w}")
    if chk.ok:
        eq = await bybit.equity("demo", key, secret)
        print(f"  баланс демо: {eq:,.2f} USD" if eq is not None else "  баланс не прочитан")


if __name__ == "__main__":
    asyncio.run(main())
