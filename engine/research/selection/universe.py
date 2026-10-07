"""30 самых ликвидных кандидатов по обороту за 2024-01…2024-06 (до валидации).

    python research/selection/universe.py  → var/data/selection/universe.txt
"""

import os

import pandas as pd

DATA = os.path.join(os.path.dirname(__file__), "..", "..", "var", "data", "selection")

if __name__ == "__main__":
    turn = {}
    for f in sorted(os.listdir(DATA)):
        if f.endswith(".parquet"):
            df = pd.read_parquet(os.path.join(DATA, f), columns=["amount"])
            turn[f[:-8]] = df.loc["2024-01":"2024-06", "amount"].sum()
    top = sorted(turn, key=turn.get, reverse=True)[:30]
    with open(os.path.join(DATA, "universe.txt"), "w") as fh:
        fh.write("\n".join(top) + "\n")
    for i, s in enumerate(top, 1):
        print(f"{i:2d}. {s:14s} {turn[s] / 1e9:8.1f} млрд $ за полгода")
