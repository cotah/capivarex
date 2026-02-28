# Use an official Python runtime as the base image
FROM python:3.11-slim

# Install system dependencies (git required by GitService, ffmpeg required by pydub)
RUN apt-get update && apt-get install -y --no-install-recommends git ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Set the working directory
WORKDIR /app

# Copy dependency files first (better layer caching)
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Copy and make start script executable
COPY start.sh /start.sh
RUN chmod +x /start.sh

# Expose the port the application uses
EXPOSE 8000

# Run FastAPI + Telegram Bot together
CMD ["/start.sh"]
