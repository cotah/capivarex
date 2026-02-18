#!/bin/bash

# SuperBot God - Backend Startup Script

echo "🚀 Starting SuperBot God Backend..."

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

# Start the FastAPI backend
echo "✅ Starting FastAPI backend on port 8000..."
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
