#!/bin/bash

# SuperBot God - Complete Startup Script (Docker Compose)

# Verify Docker is running
if ! docker info > /dev/null 2>&1; then
  echo "Docker is not running. Please start Docker Desktop."
  exit 1
fi

# Start all services
echo "Starting all services with Docker Compose..."
docker-compose up --build
