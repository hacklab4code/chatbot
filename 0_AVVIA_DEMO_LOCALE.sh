#!/usr/bin/env bash
# ==============================================================================
# SCRIPT RAPIDO AVVIO DEMO (PC UNICO / TEST LOCALE)
# ==============================================================================
# Questo script avvia tutto su questo Mac per permetterti di testare la demo
# o di fare l'esposizione direttamente da questo computer.
# ==============================================================================

set -e
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

echo "=========================================================="
echo "    🚀 AVVIO SISTEMA PRENOTAZIONI RISTORANTE (DEMO)       "
echo "=========================================================="
echo ""

# Pulizia di processi appesi sulle porte 8000 e 8001
lsof -ti:8000 | xargs kill -9 2>/dev/null || true
lsof -ti:8001 | xargs kill -9 2>/dev/null || true

# Configura .env se mancanti
[ ! -f "$ROOT_DIR/backend/.env" ] && cp "$ROOT_DIR/backend/.env.example" "$ROOT_DIR/backend/.env"
[ ! -f "$ROOT_DIR/chat/.env" ] && cp "$ROOT_DIR/chat/.env.example" "$ROOT_DIR/chat/.env"

echo "[1/2] Avvio PC 1 - Backend (FastAPI + SQLite + LLM/Mock) su porta 8000..."
BE_URL="http://localhost:8000" PYTHONPATH="$ROOT_DIR/backend" python3 -m app.main > /tmp/ristorante-backend.log 2>&1 &
BE_PID=$!

cleanup() {
    echo ""
    echo "Chiusura servizi in corso..."
    kill $BE_PID 2>/dev/null || true
    kill $CHAT_PID 2>/dev/null || true
    echo "Tutti i servizi sono stati arrestati."
    exit 0
}
trap cleanup SIGINT SIGTERM EXIT

# Attesa del backend
echo "Verifico che il backend sia attivo..."
for i in {1..20}; do
    if curl -s http://localhost:8000/health > /dev/null 2>&1; then
        break
    fi
    sleep 0.5
done

if ! curl -s http://localhost:8000/health > /dev/null 2>&1; then
    echo "❌ Errore avvio backend. Ultimi log:"
    tail -n 20 /tmp/ristorante-backend.log
    exit 1
fi
echo "✅ Backend pronto su http://localhost:8000 !"

echo "[2/2] Avvio PC 2 - Chatbot Web su porta 8001..."
BE_URL="http://localhost:8000" PYTHONPATH="$ROOT_DIR/chat" python3 -m chat_app.server > /tmp/ristorante-chat.log 2>&1 &
CHAT_PID=$!
sleep 1.5

echo ""
echo "=========================================================="
echo "  🎉 DEMO PRONTA E ATTIVA!"
echo "  - Backend (PC 1): http://localhost:8000"
echo "  - Chatbot (PC 2): http://localhost:8001 (Aperto nel browser)"
echo "  - IP locale di questo PC: $(ifconfig | grep "inet " | grep -v 127.0.0.1 | awk '{print $2}' | head -n 1)"
echo "=========================================================="
echo "Premi CTRL+C in questa finestra per fermare tutto quando hai finito."
echo ""

# Apertura automatica del browser
open http://localhost:8001 2>/dev/null || true

wait $BE_PID
