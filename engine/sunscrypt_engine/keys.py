"""Ключи Redis, общие для сервиса сигналов, исполнителей и диспетчера."""

SIGNAL = "sig:{sym}"  # последний сигнал по паре (JSON)
SIGNAL_STREAM = "signals"  # история сигналов
ZHIST = "zhist:{sym}"  # прошлые прогнозы rhat для z-оценки (список)
HB_SIGNALS = "hb:signals"  # сердцебиение сервиса сигналов
HB_ACCOUNT = "hb:acct:{id}"  # сердцебиение исполнителя кабинета (JSON)
STOP_GLOBAL = "stop:global"  # аварийная остановка всех кабинетов
STOP_ACCOUNT = "stop:acct:{id}"  # аварийная остановка / выключение кабинета
FILLS = "fills:{id}"  # исполнения кабинета (поток, читает диспетчер)
DAY_PNL = "daypnl:{id}:{day}"  # PnL на начало суток UTC — для дневного лимита
