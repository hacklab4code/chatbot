#!/usr/bin/env bash
# ==============================================================================
# AVVIO CHATBOT WEB CON LOG IN DIRETTA SUL TERMINALE
# ==============================================================================

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

# Imposta il titolo della finestra del Terminale macOS
echo -ne "\033]0;💬 CHATBOT WEB (Porta 8001)\007"

echo "=================================================================="
echo "    💬  CHATBOT WEB RISTORANTE (PORTA 8001)                      "
echo "=================================================================="
echo ""

# Pulizia di processi appesi sulla porta 8001
lsof -ti:8001 | xargs kill -9 2>/dev/null || true

# Configura .env se mancante
if [ ! -f "$ROOT_DIR/chat/.env" ]; then
    cp "$ROOT_DIR/chat/.env.example" "$ROOT_DIR/chat/.env"
fi

echo "Verifico che il Backend (porta 8000) sia attivo..."
for i in {1..10}; do
    if curl -s http://localhost:8000/health > /dev/null 2>&1; then
        echo "✅ Backend rilevato e connesso!"
        break
    fi
    sleep 0.5
done

if ! curl -s http://localhost:8000/health > /dev/null 2>&1; then
    echo "⚠️ ATTENZIONE: Il backend su porta 8000 non risponde ancora."
    echo "Avvialo con '1_AVVIA_BACKEND_TERMINALE.command' prima di usare la chat."
    echo ""
fi

echo "Avvio Chatbot Web su http://localhost:8001 ..."
open http://localhost:8001 2>/dev/null || true

BE_URL="http://localhost:8000" PYTHONPATH="$ROOT_DIR/chat" python3 -m chat_app.server
