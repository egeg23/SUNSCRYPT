"""Исполнитель одного кабинета: живой узел NautilusTrader с FollowerStrategy.

Запускает диспетчер (orchestrator.py) отдельным процессом на каждый кабинет.
Ключи — только из окружения процесса (SUNS_API_KEY / SUNS_API_SECRET), в лог
не пишутся. Реальный счёт (MAINNET) — только при SUNS_MODE=real и
SUNS_REAL_CONFIRMED=yes; диспетчер ставит это лишь при включённой владельцем
реальной торговле (бриф, правило 1). По умолчанию — демо.
"""

from __future__ import annotations

import logging
import os

import redis
from nautilus_trader.adapters.bybit import (
    BybitDataClientConfig,
    BybitDataClientFactory,
    BybitEnvironment,
    BybitExecutionClientConfig,
    BybitExecutionClientFactory,
    BybitProductType,
)
from nautilus_trader.common import Environment
from nautilus_trader.config import LiveRiskEngineConfig
from nautilus_trader.live import LiveNode
from nautilus_trader.model import AccountId, InstrumentId, TraderId

from sunscrypt_engine.follower import FollowerConfig, FollowerStrategy


def environment() -> BybitEnvironment:
    mode = os.environ.get("SUNS_MODE", "demo")
    if mode == "real":
        if os.environ.get("SUNS_REAL_CONFIRMED") != "yes":
            raise SystemExit("реальный счёт заблокирован: нет подтверждения владельца")
        return BybitEnvironment.MAINNET
    return BybitEnvironment.DEMO


def build() -> LiveNode:
    aid = os.environ["SUNS_ACCOUNT_ID"]
    pairs = os.environ.get("SUNS_PAIRS", "BTCUSDT").split(",")
    key, secret = os.environ.pop("SUNS_API_KEY"), os.environ.pop("SUNS_API_SECRET")
    env = environment()
    iids = [InstrumentId.from_str(f"{s}-LINEAR.BYBIT") for s in pairs]
    node = (
        LiveNode.builder("SUNSCRYPT", TraderId.from_str(f"SUNS-{aid[:8].upper()}"), Environment.LIVE)
        .with_reconciliation(reconciliation=True)
        .with_risk_engine_config(LiveRiskEngineConfig(bypass=False))
        .add_data_client(
            None,
            BybitDataClientFactory(),
            BybitDataClientConfig(
                product_types=[BybitProductType.LINEAR], environment=env, api_key=key, api_secret=secret
            ),
        )
        .add_exec_client(
            None,
            BybitExecutionClientFactory(),
            BybitExecutionClientConfig(
                product_types=[BybitProductType.LINEAR],
                environment=env,
                api_key=key,
                api_secret=secret,
                account_id=AccountId.from_str("BYBIT-001"),
            ),
        )
        .build()
    )
    node.add_strategy(
        FollowerStrategy(
            FollowerConfig(
                account_id=aid,
                instrument_ids=iids,
                redis=redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0")),
                capital_usd=float(os.environ.get("SUNS_CAPITAL_USD", "1000")),
                leverage=float(os.environ.get("SUNS_LEVERAGE", "1")),
                daily_loss_pct=float(os.environ.get("SUNS_DAILY_LOSS_PCT", "5")),
                max_drawdown_pct=float(os.environ.get("SUNS_MAX_DD_PCT", "40")),
                execution=os.environ.get("SUNS_EXECUTION", "maker"),
                mode=os.environ.get("SUNS_MODE", "demo"),
            )
        )
    )
    return node


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    node = build()
    if os.environ.get("SUNS_BUILD_ONLY"):
        print("узел собран:", environment())
        return
    node.run()


if __name__ == "__main__":
    main()
