FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/src

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-app.txt requirements-persistence.txt requirements-server.txt requirements-torch-cpu.txt ./
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements-torch-cpu.txt \
    && python -m pip install -r requirements-server.txt

COPY src ./src
COPY frontend ./frontend
COPY data ./data
COPY scripts ./scripts
COPY alembic.ini ./alembic.ini
COPY migrations ./migrations

RUN mkdir -p /app/logs /app/data/official_sources

EXPOSE 8010

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8010/health/live', timeout=3)"

CMD ["python", "-m", "uvicorn", "agent_runtime.api:app", "--app-dir", "src", "--host", "0.0.0.0", "--port", "8010", "--proxy-headers", "--forwarded-allow-ips=*"]
