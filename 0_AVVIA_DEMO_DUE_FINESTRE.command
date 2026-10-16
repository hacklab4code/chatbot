#!/usr/bin/env bash
# ==============================================================================
# AVVIO DEMO IN DUE FINESTRE SEPARATE DI TERMINALE (macOS)
# ==============================================================================
# Apre:
#   - Finestra 1: Backend (con log dettagliati del traffico e dati in tempo reale)
#   - Finestra 2: Chatbot Web (server web e apertura browser a http://localhost:8001)
# ==============================================================================

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

# Assicura permessi di esecuzione
chmod +x "$ROOT_DIR/1_AVVIA_BACKEND_TERMINALE.command" 2>/dev/null || true
chmod +x "$ROOT_DIR/2_AVVIA_CHATBOT_TERMINALE.command" 2>/dev/null || true

# Pulizia processi precedenti
lsof -ti:8000 | xargs kill -9 2>/dev/null || true
lsof -ti:8001 | xargs kill -9 2>/dev/null || true

echo "Apro la Finestra 1 del Terminale (Backend)..."
osascript <<EOF
tell application "Terminal"
    activate
    do script "cd \"$ROOT_DIR\" && ./1_AVVIA_BACKEND_TERMINALE.command"
end tell
EOF

sleep 2

echo "Apro la Finestra 2 del Terminale (Chatbot Web)..."
osascript <<EOF
tell application "Terminal"
    do script "cd \"$ROOT_DIR\" && ./2_AVVIA_CHATBOT_TERMINALE.command"
end tell
EOF

echo "✅ Finestre avviate!"
