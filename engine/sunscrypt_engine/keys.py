"""Ключи Redis, общие для сервиса сигналов, исполнителей и диспетчера."""

SIGNAL = "sig:{sym}"  # последний сигнал по паре (JSON)
SIGNAL_STREAM = "signals"  # история сигналов
ZHIST = "zhist:{sym}"  # прошлые прогнозы rhat для z-оценки (список)
HB_SIGNALS = "hb:signals"  # сердцебиение сервиса сигналов
HB_ACCOUNT = "hb:acct:{id}"  # сердцебиение исполнителя кабинета (JSON)
STOP_GLOBAL = "stop:global"  # аварийная остановка всех кабинетов
STOP_ACCOUNT = "stop:acct:{id}"  # аварийная остановка / выключение кабинета
FILLS = "fills:{id}"  # исполнения кабинета (поток, читает диспетчер)
DAY_TOTAL = "daytotal:{id}:{day}"  # PnL кабинета за сутки UTC (все процессы)
DAY_HALT = "dayhalt:{id}:{day}"  # дневной лимит сработал — стоим до конца суток
LIVE = "live:{id}"  # события кабинета для браузера (pub/sub): fill, hb
PAUSE_KRONOS = "pause:kronos"  # контроль дрейфа поставил Kronos на паузу (причина)
PAUSE_PAIR = "pause:pair:{sym}"  # контроль дрейфа поставил пару на паузу (причина)
