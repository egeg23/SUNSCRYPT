# engine — Kronos + NautilusTrader

Сюда переносится код исследования прошлой сессии (`kronos-bybit/`, бриф,
раздел 2.3 и этап 0): `src/fastkronos.py`, `src/finetune.py`, `nt/*`,
`tools/check_nautilus.py`. Старый бот `bot/` (pybit) не переносится.

Веса дообученной модели (`ft_small_s300`) в git не кладутся: на сервер они
попадают отдельно, выкаткой, с проверкой sha256.

Статус: ждём архив `kronos-bybit.tar.gz` и части весов от владельца.
