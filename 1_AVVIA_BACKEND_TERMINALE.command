#!/usr/bin/env bash
# ==============================================================================
# AVVIO BACKEND CON LOG IN DIRETTA SUL TERMINALE
# ==============================================================================
# Questo script avvia il Backend (FastAPI + SQLite + LLM/Mock) in primo piano.
# Mostra in tempo reale:
#  - Messaggi in arrivo da Chatbot o Voicebot
#  - Interventi della Privacy Guard (oscuramento/pseudonimizzazione)
#  - Strumenti e query al database SQLite (disponibilità, prenotazioni)
#  - Risposte generate e inviate ai client
# ==============================================================================

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

# Imposta il titolo della finestra del Terminale macOS
echo -ne "\033]0;🖥️ BACKEND RISTORANTE (Porta 8000) - LOG TRAFFICO IN TEMPO REALE\007"

echo "=================================================================="
echo "    🖥️  BACKEND RISTORANTE ZIO PIERINO (PORTA 8000)              "
echo "    Monitoraggio del traffico e passaggio dati in tempo reale    "
echo "=================================================================="
echo ""

# Pulizia di eventuali vecchi processi appesi sulla porta 8000
lsof -ti:8000 | xargs kill -9 2>/dev/null || true

# Configura .env se mancante
if [ ! -f "$ROOT_DIR/backend/.env" ]; then
    cp "$ROOT_DIR/backend/.env.example" "$ROOT_DIR/backend/.env"
fi

echo "Avvio FastAPI su http://0.0.0.0:8000 ..."
echo "------------------------------------------------------------------"
echo "Legenda Log in arrivo:"
echo " 📩 = Messaggio ricevuto da Chatbot Web o Voicebot"
echo " 🔒 = Controllo Privacy Guard e pseudonimizzazione"
echo " ⚙️ = Esecuzione strumenti (disponibilità, orari, menu)"
echo " 📝 = Creazione o modifica prenotazione nel database SQLite"
echo " 📤 = Risposta inviata al client"
echo "------------------------------------------------------------------"
echo ""

BE_URL="http://localhost:8000" PYTHONPATH="$ROOT_DIR/backend" python3 -m app.main
