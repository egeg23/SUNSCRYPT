"""Учебный Bybit для сквозного теста в CI (настоящий оттуда закрыт
гео-блоком). Отвечает на /v5/user/query-api и /v5/account/wallet-balance.

Ключи: GOOD… — правильный демо-ключ; WITHDRAW… — с правом вывода;
остальное — «API key is invalid».

    python3 e2e/fake_bybit.py 9999
"""

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

IP = "109.73.198.185"


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        key = self.headers.get("X-BAPI-API-KEY", "")
        if not key.startswith(("GOOD", "WITHDRAW")):
            return self._json({"retCode": 10003, "retMsg": "API key is invalid."})
        if self.path.startswith("/v5/user/query-api"):
            perms = {"ContractTrade": ["Order", "Position"]}
            if key.startswith("WITHDRAW"):
                perms["Wallet"] = ["AccountTransfer", "Withdraw"]
            return self._json(
                {"retCode": 0, "result": {"readOnly": 0, "permissions": perms, "ips": [IP], "uta": 1}}
            )
        if self.path.startswith("/v5/account/wallet-balance"):
            return self._json({"retCode": 0, "result": {"list": [{"totalEquity": "100000"}]}})
        self.send_response(404)
        self.end_headers()

    def _json(self, body):
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


ThreadingHTTPServer(("0.0.0.0", int(sys.argv[1])), Handler).serve_forever()
