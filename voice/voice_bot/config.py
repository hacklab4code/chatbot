"""Configurazione del voice-bot, da variabili d'ambiente o file .env."""
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

DATA_DIR = Path(os.getenv("VOICE_DATA_DIR", str(BASE_DIR / "data")))  # vault e chiave restano qui
PSEUDO_SECRET = os.getenv("PSEUDO_SECRET", "")

# Speech-to-text locale (faster-whisper). Modelli: tiny, base, small, medium, large-v3
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "auto")  # auto | cpu | cuda
WHISPER_MODELS_DIR = Path(os.getenv("WHISPER_MODELS_DIR", str(BASE_DIR / "models")))
LANGUAGE = "it"

# Registrazione audio
SAMPLE_RATE = 16000
MIC_DEVICE = os.getenv("MIC_DEVICE") or None  # indice o nome; vuoto = predefinito
SILENCE_SECONDS = float(os.getenv("SILENCE_SECONDS", "1.2"))  # pausa che chiude la frase
MAX_UTTERANCE_SECONDS = float(os.getenv("MAX_UTTERANCE_SECONDS", "20"))
WAIT_FOR_SPEECH_SECONDS = float(os.getenv("WAIT_FOR_SPEECH_SECONDS", "15"))

# Text-to-speech locale (voci di sistema: SAPI su Windows, NSSpeech su macOS, eSpeak su Linux)
TTS_RATE = int(os.getenv("TTS_RATE", "175"))
TTS_VOICE = os.getenv("TTS_VOICE", "")  # parte del nome della voce; vuoto = prima voce italiana
