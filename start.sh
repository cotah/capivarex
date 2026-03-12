#!/bin/bash
# start.sh — Inicia FastAPI + Telegram Bot em simultâneo
# O bot é isolado: se crashar, o FastAPI continua a correr.

echo "Starting Jarvis..."

# --- Telegram Bot (isolado) ------------------------------------------------
# Lanca num sub-shell com trap para que um crash nunca mate o uvicorn.
echo "Starting Telegram Bot (polling)..."
(
    python -m telegram_bot.main
    BOT_EXIT=$?
    if [ $BOT_EXIT -ne 0 ]; then
        echo "WARNING: Telegram bot exited with code $BOT_EXIT — webapp continues running"
    fi
) &
TELEGRAM_PID=$!
echo "  Telegram PID: $TELEGRAM_PID"

# --- FastAPI (processo principal) -------------------------------------------
echo "Starting FastAPI (uvicorn)..."
PORT=${PORT:-8000}
uvicorn api.main:app --host 0.0.0.0 --port "$PORT" --workers 1 &
UVICORN_PID=$!
echo "  FastAPI PID:  $UVICORN_PID"

echo "Both services started!"

# --- Supervisao -------------------------------------------------------------
# Espera APENAS pelo uvicorn. Se o FastAPI morrer, encerramos tudo.
# Se o bot morrer, o uvicorn continua a servir a webapp normalmente.
wait $UVICORN_PID
UVICORN_EXIT=$?

echo "FastAPI stopped (exit code: $UVICORN_EXIT). Shutting down bot..."
kill $TELEGRAM_PID 2>/dev/null || true
exit $UVICORN_EXIT
