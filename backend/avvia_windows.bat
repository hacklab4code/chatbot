@echo off
title PC1 - BACKEND RISTORANTE
cd /d %~dp0
echo ===================================================
echo     AVVIO PC 1: BACKEND (FastAPI + SQLite + LLM)
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
echo Backend in ascolto su http://0.0.0.0:8000
python -m app.main
pause
