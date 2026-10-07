"""Реестр версий модели Kronos (этап 8) — на томе /models.

    /models/ft_small_s300/          исходная модель (качается при выкатке)
    /models/registry/<версия>/      выпущенные дообученные версии
    /models/registry/CHAMPION       имя текущего чемпиона (одна строка)

Чемпиона читает сервис сигналов и сам переключается на новую версию. Кто,
когда и почему выпустил или отклонил версию — в базе (model_events) и в
админке.
"""

from __future__ import annotations

import os

ROOT = os.environ.get("SUNS_MODELS_ROOT", "/models")
BASE = os.environ.get("SIGNAL_MODEL_NAME", "ft_small_s300")


def reg_dir() -> str:
    return os.path.join(ROOT, "registry")


def path_of(version: str) -> str:
    return os.path.join(ROOT, BASE) if version == BASE else os.path.join(reg_dir(), version)


def champion() -> str:
    """Имя чемпиона; нет указателя или папки версии — исходная модель."""
    try:
        with open(os.path.join(reg_dir(), "CHAMPION")) as f:
            v = f.read().strip()
    except OSError:
        return BASE
    return v if v and os.path.isdir(path_of(v)) else BASE


def set_champion(version: str) -> None:
    """Атомарно: сервис сигналов не прочтёт полузаписанный файл."""
    os.makedirs(reg_dir(), exist_ok=True)
    tmp = os.path.join(reg_dir(), ".CHAMPION.tmp")
    with open(tmp, "w") as f:
        f.write(version + "\n")
    os.replace(tmp, os.path.join(reg_dir(), "CHAMPION"))
