"""Run KronosStrategy on a NautilusTrader LiveNode against Bybit (DEMO by default).

  BYBIT_DEMO_API_KEY=... BYBIT_DEMO_API_SECRET=... python nt/live.py --tf 1h --execution maker
Keys come only from env vars (the adapter reads BYBIT_DEMO_API_KEY / BYBIT_DEMO_API_SECRET for DEMO,
BYBIT_TESTNET_API_KEY / ..._SECRET for TESTNET, BYBIT_API_KEY / ..._SECRET for MAINNET).
MAINNET needs --i-accept-real-money-risk; it is never the default.
"""
from __future__ import annotations

import argparse
import os
import sys

from nautilus_trader.adapters.bybit import (BybitDataClientConfig, BybitDataClientFactory, BybitEnvironment,
                                            BybitExecutionClientConfig, BybitExecutionClientFactory,
                                            BybitProductType)
from nautilus_trader.common import Environment
from nautilus_trader.config import LiveRiskEngineConfig
from nautilus_trader.live import LiveNode
from nautilus_trader.model import AccountId, BarType, InstrumentId, TraderId

sys.path.insert(0, os.path.dirname(__file__))
from signals import KronosSignals, MomentumSignals  # noqa: E402
from strategy import KronosStrategy, KronosStrategyConfig  # noqa: E402

from paths import DATA_DIR, MODEL_DIR, RESULTS_DIR  # noqa: E402
TF = {"1h": (60, 8, "1-HOUR"), "4h": (240, 6, "4-HOUR")}


def build(a) -> LiveNode:
    env = {"demo": BybitEnvironment.DEMO, "testnet": BybitEnvironment.TESTNET,
           "mainnet": BybitEnvironment.MAINNET}[a.env]
    bar_min, H, spec = TF[a.tf]
    iids = [InstrumentId.from_str(f"{s}-LINEAR.BYBIT") for s in a.symbols.split(",")]
    bts = [BarType.from_str(f"{i}-{spec}-LAST-EXTERNAL") for i in iids]
    risk = LiveRiskEngineConfig(bypass=False)
    node = (
        LiveNode.builder("KRONOS-BYBIT", TraderId.from_str("KRONOS-001"), Environment.LIVE)
        .with_reconciliation(reconciliation=True)
        .with_risk_engine_config(risk)
        .add_data_client(None, BybitDataClientFactory(),
                         BybitDataClientConfig(product_types=[BybitProductType.LINEAR], environment=env))
        .add_exec_client(None, BybitExecutionClientFactory(),
                         BybitExecutionClientConfig(product_types=[BybitProductType.LINEAR], environment=env,
                                                    account_id=AccountId.from_str("BYBIT-001")))
        .build()
    )
    src = MomentumSignals(H) if a.signals == "momentum" else \
        KronosSignals(model_path=a.model_path, horizon=H, bar_minutes=bar_min)
    node.add_strategy(KronosStrategy(KronosStrategyConfig(
        instrument_ids=iids, bar_types=bts, signal_source=src, horizon=H, bar_minutes=bar_min,
        notional_usd=a.notional, execution=a.execution, use_z=(a.signals != "momentum"),
        max_daily_loss_usd=a.max_daily_loss, kill_file=a.kill_file)))
    return node


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", default="demo", choices=["demo", "testnet", "mainnet"])
    ap.add_argument("--i-accept-real-money-risk", dest="real", action="store_true")
    ap.add_argument("--tf", default="1h", choices=list(TF))
    ap.add_argument("--signals", default="kronos", choices=["kronos", "momentum"])
    ap.add_argument("--symbols", default="BTCUSDT,ETHUSDT")
    ap.add_argument("--model_path", default=MODEL_DIR)
    ap.add_argument("--execution", default="maker", choices=["taker", "maker"])
    ap.add_argument("--notional", type=float, default=100.0)
    ap.add_argument("--max_daily_loss", type=float, default=30.0)
    ap.add_argument("--kill_file", default="KILL")
    ap.add_argument("--build-only", dest="build_only", action="store_true")
    a = ap.parse_args()
    if a.env == "mainnet" and not a.real:
        raise SystemExit("mainnet is locked: pass --i-accept-real-money-risk deliberately")
    node = build(a)
    if a.build_only:
        print("node built OK:", a.env, a.tf, a.signals, a.symbols)
        return
    node.run()


if __name__ == "__main__":
    main()
