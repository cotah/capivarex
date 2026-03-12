#!/bin/bash
# start_bot.sh — Inicia APENAS o Telegram Bot (polling)
# Usado pelo serviço capivarex-bot no Railway / Cloud Run
set -e
echo "Starting CAPIVAREX Telegram Bot..."
exec python -m telegram_bot.main
