#!/bin/bash
set -e

echo "Starting AutoFlow locally..."

# Start Redis & Postgres (assuming installed via brew)
echo "Ensuring DB and Redis are running..."
brew services start postgresql@16 || true
brew services start redis || true

# Setup DB user/db if missing
echo "Configuring PostgreSQL..."
psql postgres -c "CREATE USER autoflow WITH PASSWORD 'autoflow_dev_password';" || true
psql postgres -c "ALTER USER autoflow CREATEDB;" || true
psql postgres -c "CREATE DATABASE autoflow OWNER autoflow;" || true

# Run migrations
echo "Running migrations..."
cd backend
uv run alembic upgrade head
cd ..

# Start backend services
echo "Starting backend API..."
cd backend
uv run fastapi run src/autoflow/main.py --host 0.0.0.0 --port 8000 &
API_PID=$!

echo "Starting Celery Worker..."
uv run celery -A autoflow.execution.celery_app worker --loglevel=info --concurrency=4 -Q default,execution,browser &
WORKER_PID=$!

# Start Frontend
echo "Starting frontend dev server..."
cd ../frontend
pnpm dev &
FRONTEND_PID=$!

cleanup() {
    echo "Stopping services..."
    kill $API_PID $WORKER_PID $FRONTEND_PID 2>/dev/null
    exit
}

trap cleanup SIGINT SIGTERM

echo "AutoFlow is running!"
echo "Dashboard: http://localhost:5173"
echo "API Docs: http://localhost:8000/docs"
echo "Press Ctrl+C to stop all services."

# Wait for all background processes
wait
