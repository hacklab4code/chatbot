@echo off
title PC3 - VOICEBOT RISTORANTE
cd /d %~dp0
echo ===================================================
echo     AVVIO PC 3: VOICEBOT (Whisper STT + TTS)
echo ===================================================
if not exist .venv (
    echo Creazione ambiente virtuale Python...
    python -m venv .venv
    call .venv\Scripts\activate.bat
    pip install -r requirements.txt
) else (
    call .venv\Scripts\activate.bat
)
if not exist .env (
    copy .env.example .env
)
echo.
echo Scegli come avviare il voicebot:
echo [1] Normale (microfono + voce di risposta)
echo [2] Modalita tastiera (scrivi da tastiera, risposta letta a voce)
echo.
set /p scelta="Scelta (1 o 2, predefinito 1): "
if "%scelta%"=="2" (
    python -m voice_bot.main --text
) else (
    python -m voice_bot.main
)
pause
