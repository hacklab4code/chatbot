#!/usr/bin/env bash
# ==============================================================================
# AVVIO DEMO COMPLETA IN TRE FINESTRE SEPARATE DI TERMINALE (macOS)
# ==============================================================================
# Apre:
#   - Finestra 1: Backend (FastAPI + SQLite + LLM con log traffico in diretta)
#   - Finestra 2: Chatbot Web (apertura browser http://localhost:8001)
#   - Finestra 3: Voicebot (Whisper STT + Sintesi Vocale)
# ==============================================================================

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

chmod +x "$ROOT_DIR"/*.command 2>/dev/null || true

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

sleep 1

echo "Apro la Finestra 3 del Terminale (Voicebot)..."
osascript <<EOF
tell application "Terminal"
    do script "cd \"$ROOT_DIR\" && ./3_AVVIA_VOICE_TERMINALE.command"
end tell
EOF

echo "✅ Tutte e 3 le finestre avviate!"
