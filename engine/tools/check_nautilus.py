"""Check for new NautilusTrader versions and test them against our integration before upgrading.

Sources (all public, no keys):
  * PyPI  https://pypi.org/pypi/nautilus_trader/json            - stable and pre-releases (rc)
  * GitHub tags (git ls-remote)                                - published at the same time as PyPI by their CI
  * Nightly index https://packages.nautechsystems.io/simple/   - daily dev builds from the `develop` branch

Usage:
  python tools/check_nautilus.py                      # report only
  python tools/check_nautilus.py --test               # install the newest release in a temp venv and run smoke tests
  python tools/check_nautilus.py --test --channel nightly
Exit code: 0 up to date / candidate passed, 1 candidate failed, 2 network error.
Upgrade policy: the pinned version lives in requirements-nautilus.txt; bump it only after --test passes.
The smoke backtest runs the model-free momentum strategy on tests/fixtures (BTC/ETH 4h), so it needs no model weights.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PIN_FILE = os.path.join(ROOT, "requirements-nautilus.txt")
NIGHTLY = "https://packages.nautechsystems.io/simple/nautilus-trader/"
BASELINE = os.path.join(ROOT, "tests", "nautilus_baseline.json")


def vkey(v: str):
    m = re.match(r"(\d+)\.(\d+)\.(\d+)(?:(rc)(\d+))?(?:\.dev(\d+))?", v)
    if not m:
        return (0,)
    a, b, c, rc, rcn, dev = m.groups()
    return (int(a), int(b), int(c), 0 if rc else 1, int(rcn or 0), int(dev or 10**12))


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "kronos-bybit-version-check/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode()


def pinned():
    for line in open(PIN_FILE):
        m = re.match(r"\s*nautilus_trader==([^\s#]+)", line)
        if m:
            return m.group(1)
    raise SystemExit("no nautilus_trader pin in " + PIN_FILE)


def pypi():
    d = json.loads(get("https://pypi.org/pypi/nautilus_trader/json"))
    rel = [v for v, files in d["releases"].items() if files]
    pre = max(rel, key=vkey)
    return d["info"]["version"], pre, {v: d["releases"][v][0]["upload_time"] for v in rel}


def github_tags():
    out = subprocess.run(["git", "ls-remote", "--tags", "https://github.com/nautechsystems/nautilus_trader"],
                         capture_output=True, text=True, timeout=60).stdout
    tags = {l.split("refs/tags/")[1].lstrip("v") for l in out.splitlines() if "^{}" not in l and "refs/tags/v" in l}
    return max(tags, key=vkey) if tags else None


def nightly():
    py = f"cp{sys.version_info.major}{sys.version_info.minor}"
    html = get(NIGHTLY)
    vs = re.findall(rf"nautilus_trader-([0-9][^-]*)-{py}-{py}-manylinux[^\"#<]*x86_64\.whl", html)
    return max(vs, key=vkey) if vs else None


def smoke(spec: str, extra_index: str | None) -> tuple[bool, str]:
    """Fresh venv with the candidate; build the live node and run the replay backtest; compare with baseline."""
    with tempfile.TemporaryDirectory() as d:
        venv = os.path.join(d, "venv")
        subprocess.run([sys.executable, "-m", "venv", venv], check=True)
        pip = [os.path.join(venv, "bin", "pip"), "install", "-q", "--pre", spec, "pandas", "pyarrow", "numpy"]
        if extra_index:
            pip += ["--extra-index-url", extra_index]
        r = subprocess.run(pip, capture_output=True, text=True)
        if r.returncode:
            return False, "install failed: " + r.stderr[-500:]
        py = os.path.join(venv, "bin", "python")
        env = dict(os.environ, BYBIT_DEMO_API_KEY="dummy", BYBIT_DEMO_API_SECRET="dummy",
                   SUNS_ENGINE_DATA=os.path.join(ROOT, "tests", "fixtures"), SUNS_ENGINE_RESULTS=d)
        bt = ["sunscrypt_engine/backtest.py", "--tf", "4h", "--signals", "momentum", "--symbols", "BTCUSDT,ETHUSDT"]
        steps = [
            [py, "-c", "import nautilus_trader as n; print(n.__version__)"],
            [py, "sunscrypt_engine/live.py", "--signals", "momentum", "--build-only"],
            [py, *bt, "--execution", "taker"],
            [py, *bt, "--execution", "maker"],
        ]
        log = []
        for cmd in steps:
            r = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT, env=env, timeout=1800)
            tail = "\n".join(l for l in r.stdout.splitlines() if l.startswith(("[", "node", "2.", "1."))) or r.stderr[-800:]
            log.append(f"$ {' '.join(cmd[1:])}\n{tail}")
            if r.returncode:
                return False, "\n".join(log)
        out = "\n".join(log)
        if os.path.exists(BASELINE):          # results must not drift silently between versions
            base = json.load(open(BASELINE))
            for k, v in base.items():
                m = re.search(re.escape(k) + r"\] final balance ([0-9.]+)", out)
                if not m or abs(float(m.group(1)) - v) > 0.005 * v:
                    return False, out + f"\nresult drift for {k}: baseline {v}, got {m.group(1) if m else 'n/a'}"
        return True, out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--channel", default="release", choices=["release", "stable", "nightly"])
    a = ap.parse_args()
    try:
        cur = pinned()
        stable, pre, times = pypi()
        tag = github_tags()
        night = nightly()
    except Exception as e:
        print("network error:", e)
        return 2
    print(f"pinned        : {cur}")
    print(f"PyPI stable   : {stable}   ({times.get(stable, '')})")
    print(f"PyPI newest   : {pre}   ({times.get(pre, '')})")
    print(f"GitHub tag    : {tag}   ({'same as PyPI' if tag == pre else 'DIFFERS from PyPI'})")
    print(f"nightly build : {night}")
    cand = {"stable": stable, "release": pre, "nightly": night}[a.channel]
    if vkey(cand) <= vkey(cur):
        print(f"up to date on channel '{a.channel}'")
        return 0
    print(f"newer on channel '{a.channel}': {cand}")
    if not a.test:
        return 0
    ok, log = smoke(f"nautilus_trader=={cand}", "https://packages.nautechsystems.io/simple" if a.channel == "nightly" else None)
    print(log)
    print(("PASS: safe to bump requirements-nautilus.txt to " if ok else "FAIL: keep ") + (cand if ok else cur))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
