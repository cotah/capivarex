#!/bin/bash
# start.sh — Inicia FastAPI + Telegram Bot + ARQ Worker em simultâneo
# Cada serviço é isolado: se crashar, os outros continuam a correr.

echo "Starting CAPIVAREX..."

# --- Telegram Bot (isolado) ------------------------------------------------
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

# --- ARQ Worker (isolado, only if REDIS_URL is set) --------------------------
if [ -n "$REDIS_URL" ]; then
    echo "Starting ARQ Worker (background tasks)..."
    (
        python -m arq worker.WorkerSettings
        ARQ_EXIT=$?
        if [ $ARQ_EXIT -ne 0 ]; then
            echo "WARNING: ARQ worker exited with code $ARQ_EXIT — webapp continues running"
        fi
    ) &
    ARQ_PID=$!
    echo "  ARQ PID:      $ARQ_PID"
else
    echo "  ARQ Worker: SKIPPED (REDIS_URL not set)"
fi

# --- FastAPI (processo principal) -------------------------------------------
echo "Starting FastAPI (uvicorn)..."
PORT=${PORT:-8000}
uvicorn api.main:app --host 0.0.0.0 --port "$PORT" --workers 1 &
UVICORN_PID=$!
echo "  FastAPI PID:  $UVICORN_PID"

echo "All services started!"

# --- Supervisao -------------------------------------------------------------
# Espera APENAS pelo uvicorn. Se o FastAPI morrer, encerramos tudo.
wait $UVICORN_PID
UVICORN_EXIT=$?

echo "FastAPI stopped (exit code: $UVICORN_EXIT). Shutting down..."
kill $TELEGRAM_PID 2>/dev/null || true
[ -n "$ARQ_PID" ] && kill $ARQ_PID 2>/dev/null || true
exit $UVICORN_EXIT
