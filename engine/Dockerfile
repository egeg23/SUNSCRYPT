# Образ движка: сервис сигналов (Kronos) и диспетчер с исполнителями
# (NautilusTrader). Контекст сборки — корень репозитория: диспетчеру нужен
# код бэкенда (модели БД, шифрование).
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

RUN pip install --index-url https://download.pytorch.org/whl/cpu torch==2.14.1
COPY engine/requirements-engine.txt backend/requirements.txt /tmp/
RUN pip install --pre -r /tmp/requirements-engine.txt -r /tmp/requirements.txt

COPY backend/app /app/backend/app
COPY engine/sunscrypt_engine /app/engine/sunscrypt_engine
COPY engine/vendor /app/engine/vendor

ENV PYTHONPATH=/app/backend:/app/engine HF_HOME=/models/hf
RUN useradd --system --uid 10001 --create-home app && mkdir -p /models && chown app /models
USER app
WORKDIR /app/engine
CMD ["python", "-m", "sunscrypt_engine.orchestrator"]
