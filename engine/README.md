# engine

Торговый движок SUNSCRYPT, перенесён из исследования `kronos-bybit`.

| файл | что |
|---|---|
| `sunscrypt_engine/fastkronos.py` | инференс Kronos с KV-кэшем (результат идентичен оригиналу, в 36–51 раз быстрее на CPU), отдаёт все сэмплы |
| `sunscrypt_engine/finetune.py` | дообучение (teacher forcing, нормализация только по прошлому) |
| `sunscrypt_engine/strategy.py`, `signals.py` | стратегия для NautilusTrader и источники сигнала (Kronos, повтор, моментум) |
| `sunscrypt_engine/backtest.py`, `live.py` | бэктест на движке Nautilus и живой узел Bybit (DEMO по умолчанию) |
| `tools/check_nautilus.py` | сверка закреплённой версии Nautilus с PyPI/GitHub/nightly и smoke-тест кандидата |
| `vendor/kronos/` | неизменённый пакет `model/` из shiyu-coder/Kronos (MIT) |
| `research/` | скрипты исследования и `report.json` с цифрами |
| `tests/fixtures/` | свечи BTC/ETH 4h для smoke-теста |

Пути: `SUNS_ENGINE_DATA` (свечи), `SUNS_ENGINE_RESULTS` (результаты), `SUNS_MODEL_DIR` (веса дообученной модели,
по умолчанию `engine/var/models/ft_small_s300`). Каталог `engine/var/` в git не попадает.

Установка: `pip install -r requirements-nautilus.txt` (torch — CPU-сборка, см. комментарий в файле).
