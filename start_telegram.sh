#!/bin/bash

# SuperBot God - Telegram Bot Startup Script

echo "📱 Starting SuperBot God Telegram Bot..."

# Navigate to project directory
cd "$(dirname "$0")/superbot god" || exit

# Activate virtual environment
if [ -f ".venv/Scripts/activate" ]; then
    source ".venv/Scripts/activate"
elif [ -f ".venv/bin/activate" ]; then
    source ".venv/bin/activate"
else
    echo "❌ Virtual environment not found!"
    exit 1
fi

# Check if .env file exists
if [ ! -f ".env" ]; then
    echo "⚠️  Warning: .env file not found!"
    echo "Please create a .env file with your API keys."
    echo "You can use .env.example as a template."
    exit 1
fi

# Check if backend is running
if ! curl -s http://localhost:8000/api/health > /dev/null; then
    echo "⚠️  Warning: Backend is not running!"
    echo "Please start the backend first using start_backend.sh"
    echo ""
    read -p "Do you want to continue anyway? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Start the Telegram bot
echo "✅ Starting Telegram bot..."
python -m telegram_bot.main
