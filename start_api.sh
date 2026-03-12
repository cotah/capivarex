#!/bin/bash
# start_api.sh — Inicia APENAS o FastAPI (uvicorn)
# Usado pelo serviço capivarex-api no Railway / Cloud Run
set -e
echo "Starting CAPIVAREX FastAPI..."
PORT=${PORT:-8000}
exec uvicorn api.main:app --host 0.0.0.0 --port "$PORT" --workers 1
