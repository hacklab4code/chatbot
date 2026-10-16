#!/usr/bin/env bash
cd "$(dirname "$0")"
echo "=== AVVIO PC 1: BACKEND (FastAPI + SQLite + LLM) ==="
if [ ! -f ".venv/bin/activate" ]; then
    echo "Creazione ambiente virtuale..."
    rm -rf .venv
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
else
    source .venv/bin/activate
fi
if [ ! -f ".env" ]; then
    cp .env.example .env
fi
echo "Backend in ascolto su http://0.0.0.0:8000..."
python3 -m app.main
