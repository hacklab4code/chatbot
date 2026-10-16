#!/usr/bin/env bash
cd "$(dirname "$0")"
echo "=== AVVIO PC 2: CHATBOT (Web su http://localhost:8001) ==="
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
echo "Apertura browser su http://localhost:8001..."
open http://localhost:8001 2>/dev/null || xdg-open http://localhost:8001 2>/dev/null || true
echo "Server chat in avvio..."
python3 -m chat_app.server
