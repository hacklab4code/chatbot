@echo off
title PC2 - CHATBOT RISTORANTE
cd /d %~dp0
echo ===================================================
echo     AVVIO PC 2: CHATBOT (Web su http://localhost:8001)
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
echo Apertura del browser su http://localhost:8001...
start http://localhost:8001
echo Server chat in avvio...
python -m chat_app.server
pause
