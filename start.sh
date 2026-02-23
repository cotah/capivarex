#!/bin/bash
# start.sh — Inicia FastAPI + Telegram Bot em simultâneo

set -e

echo "🚀 Starting Jarvis..."

# Inicia o FastAPI em background
echo "▶ Starting FastAPI (uvicorn)..."
uvicorn api.main:app --host 0.0.0.0 --port 8000 &
UVICORN_PID=$!

# Aguarda 3 segundos para o FastAPI iniciar
sleep 3

# Inicia o Telegram Bot polling em background
echo "▶ Starting Telegram Bot (polling)..."
python -m telegram_bot.main &
TELEGRAM_PID=$!

echo "✅ Both services started!"
echo "   FastAPI PID:  $UVICORN_PID"
echo "   Telegram PID: $TELEGRAM_PID"

# Aguarda ambos os processos — se um morrer, mata o outro
wait -n $UVICORN_PID $TELEGRAM_PID
EXIT_CODE=$?

echo "❌ One service stopped (exit code: $EXIT_CODE). Shutting down..."
kill $UVICORN_PID $TELEGRAM_PID 2>/dev/null || true
exit $EXIT_CODE
