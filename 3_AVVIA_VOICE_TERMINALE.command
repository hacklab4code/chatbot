#!/usr/bin/env bash
# ==============================================================================
# AVVIO VOICEBOT CON FINESTRA TERMINALE DEDICATA (Whisper STT + TTS)
# ==============================================================================

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR/voice"

# Imposta il titolo della finestra del Terminale macOS
echo -ne "\033]0;🎙️ VOICEBOT (Whisper STT + Sintesi Vocale TTS)\007"

echo "=================================================================="
echo "    🎙️  VOICEBOT RISTORANTE ZIO PIERINO (Whisper + TTS)          "
echo "=================================================================="
echo ""

# Attivazione virtualenv
if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

# Configura .env se mancante
if [ ! -f ".env" ]; then
    cp .env.example .env
fi

echo "Verifico che il Backend (porta 8000) sia attivo..."
for i in {1..10}; do
    if curl -s http://localhost:8000/health > /dev/null 2>&1; then
        echo "✅ Backend connesso su http://localhost:8000 !"
        break
    fi
    sleep 0.5
done

if ! curl -s http://localhost:8000/health > /dev/null 2>&1; then
    echo "⚠️ ATTENZIONE: Il backend non risponde su http://localhost:8000."
    echo "Avvialo con '1_AVVIA_BACKEND_TERMINALE.command' prima di usare il voicebot."
    echo ""
fi

echo "Come desideri interagire con il Voicebot?"
echo "  [1] 🎙️ Microfono + Altoparlanti (parli tu e il bot ti risponde a voce)"
echo "  [2] ⌨️  Tastiera + Voce (scrivi da tastiera e il bot ti risponde a voce)"
echo "  [3] 📄 Solo Testo (scrivi e leggi solo su terminale)"
echo ""
printf "Scegli un'opzione [1, 2 o 3, premi Invio per 1]: "
read SCELTA

if [ "$SCELTA" = "2" ]; then
    python3 -m voice_bot.main --text
elif [ "$SCELTA" = "3" ]; then
    python3 -m voice_bot.main --text --no-tts
else
    python3 -m voice_bot.main
fi
