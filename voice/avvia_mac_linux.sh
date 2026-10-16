#!/usr/bin/env bash
cd "$(dirname "$0")"
echo "=== AVVIO PC 3: VOICEBOT (Whisper STT + TTS) ==="
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

echo "Come vuoi avviare il voicebot?"
echo "[1] Microfono + Altoparlanti"
echo "[2] Tastiera (scrivi tu, risponde a voce) -- consigliato se non hai microfono configurato"
echo "[3] Solo testo da terminale (--text --no-tts)"
printf "Scelta [1, 2 o 3]: "
read SCELTA

if [ "$SCELTA" = "2" ]; then
    python3 -m voice_bot.main --text
elif [ "$SCELTA" = "3" ]; then
    python3 -m voice_bot.main --text --no-tts
else
    python3 -m voice_bot.main
fi
