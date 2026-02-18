#!/bin/bash

# SuperBot God - Complete Startup Script
# This script starts both the backend and Telegram bot

echo "🚀 Starting SuperBot God - Complete System..."
echo ""

# Navigate to project directory
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/superbot god" || exit

# Check if .env file exists
if [ ! -f ".env" ]; then
    echo "❌ Error: .env file not found!"
    echo "Please create a .env file with your API keys."
    echo "You can use .env.example as a template."
    exit 1
fi

# Activate virtual environment
if [ -f ".venv/Scripts/activate" ]; then
    source ".venv/Scripts/activate"
elif [ -f ".venv/bin/activate" ]; then
    source ".venv/bin/activate"
else
    echo "❌ Virtual environment not found!"
    echo "Creating virtual environment..."
    python3 -m venv .venv
    source ".venv/bin/activate"
    pip install -r requirements.txt
fi

echo "✅ Virtual environment activated"
echo ""

# Start backend in background
echo "🔧 Starting FastAPI backend..."
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000 > /tmp/superbot_backend.log 2>&1 &
BACKEND_PID=$!
echo "✅ Backend started (PID: $BACKEND_PID)"
echo "   Logs: /tmp/superbot_backend.log"
echo ""

# Wait for backend to be ready
echo "⏳ Waiting for backend to be ready..."
for i in {1..30}; do
    if curl -s http://localhost:8000/api/health > /dev/null 2>&1; then
        echo "✅ Backend is ready!"
        break
    fi
    sleep 1
    if [ $i -eq 30 ]; then
        echo "❌ Backend failed to start. Check logs at /tmp/superbot_backend.log"
        kill $BACKEND_PID 2>/dev/null
        exit 1
    fi
done
echo ""

# Start Telegram bot
echo "📱 Starting Telegram bot..."
python -m telegram_bot.main &
TELEGRAM_PID=$!
echo "✅ Telegram bot started (PID: $TELEGRAM_PID)"
echo ""

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🎉 SuperBot God is now running!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "📊 Services:"
echo "   • Backend API: http://localhost:8000"
echo "   • API Docs: http://localhost:8000/docs"
echo "   • Telegram Bot: Active"
echo ""
echo "📝 Process IDs:"
echo "   • Backend: $BACKEND_PID"
echo "   • Telegram: $TELEGRAM_PID"
echo ""
echo "🛑 To stop all services, press Ctrl+C"
echo ""

# Function to cleanup on exit
cleanup() {
    echo ""
    echo "🛑 Stopping services..."
    kill $BACKEND_PID 2>/dev/null
    kill $TELEGRAM_PID 2>/dev/null
    echo "✅ All services stopped"
    exit 0
}

# Trap Ctrl+C and call cleanup
trap cleanup INT TERM

# Wait for processes
wait
