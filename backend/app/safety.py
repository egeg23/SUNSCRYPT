"""Жёсткие правила брифа, зашитые в код. Их нельзя ослабить настройкой:
меняются только правкой кода с ревью.

- Плечо не выше 2×, по умолчанию 1×.
- По умолчанию всё в демо; реальный счёт заблокирован, пока владелец явно
  не включит глобальный флаг (system_flags.real_trading_enabled).
"""

from enum import StrEnum

MAX_LEVERAGE = 2
DEFAULT_LEVERAGE = 1


class Mode(StrEnum):
    DEMO = "demo"
    REAL = "real"


DEFAULT_MODE = Mode.DEMO


def check_leverage(value: float) -> float:
    """Плечо в пределах (0, MAX_LEVERAGE]; иначе ValueError."""
    if not 0 < value <= MAX_LEVERAGE:
        raise ValueError(f"Плечо должно быть больше 0 и не выше {MAX_LEVERAGE}×")
    return value


def real_mode_allowed(real_trading_enabled: bool, global_stop: bool) -> bool:
    """Реальный режим возможен только при включённом владельцем флаге и
    без аварийной остановки."""
    return real_trading_enabled and not global_stop
