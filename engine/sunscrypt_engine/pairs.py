"""Список пар и стратегия для каждой — из версионного конфига
engine/config/pairs.json (бриф, этап 7: «список пар — в конфиге с версией»).
Стратегии: kronos_1h (модель) и momentum_4h (без модели)."""

from __future__ import annotations

import json
import os

DEFAULT = os.path.join(os.path.dirname(__file__), "..", "config", "pairs.json")
STRATEGIES = {"kronos_1h", "momentum_4h"}


def load(path: str | None = None) -> dict:
    with open(path or os.environ.get("SUNS_PAIRS_FILE", DEFAULT)) as fh:
        cfg = json.load(fh)
    for p in cfg["pairs"]:
        if p["strategy"] not in STRATEGIES:
            raise ValueError(f"неизвестная стратегия {p['strategy']} у {p['sym']}")
    return cfg


def symbols(path: str | None = None) -> list[str]:
    return [p["sym"] for p in load(path)["pairs"]]
