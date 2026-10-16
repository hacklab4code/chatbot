"""Configurazione del chat-bot, da variabili d'ambiente o file .env."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

_env = BASE_DIR / ".env"
if _env.exists():
    for _line in _env.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

BE_URL = os.getenv("BE_URL", "http://localhost:8000").rstrip("/")  # IP del BE nella LAN
BE_API_KEY = os.getenv("BE_API_KEY", "")
BE_TIMEOUT = float(os.getenv("BE_TIMEOUT", "300"))

CHAT_HOST = os.getenv("CHAT_HOST", "0.0.0.0")
CHAT_PORT = int(os.getenv("CHAT_PORT", "8001"))

DATA_DIR = Path(os.getenv("CHAT_DATA_DIR", str(BASE_DIR / "data")))  # vault e chiave restano qui
PSEUDO_SECRET = os.getenv("PSEUDO_SECRET", "")
