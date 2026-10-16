"""Configurazione del backend, letta da variabili d'ambiente (o file .env)."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    """Carica un eventuale file .env senza dipendenze esterne."""
    env_file = BASE_DIR / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()

# Server
HOST = os.getenv("BE_HOST", "0.0.0.0")  # 0.0.0.0 = raggiungibile dalla LAN
PORT = int(os.getenv("BE_PORT", "8000"))
API_KEY = os.getenv("BE_API_KEY", "")  # se valorizzata, i client devono inviarla in X-API-Key

# Database
DB_PATH = Path(os.getenv("BE_DB_PATH", str(BASE_DIR / "data" / "ristorante.db")))

# LLM locale (Ollama)
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen3-coder:30b")  # modello testato; alternative: qwen2.5:7b, llama3.1:8b
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.2"))
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "240"))
LLM_MAX_TOOL_ROUNDS = int(os.getenv("LLM_MAX_TOOL_ROUNDS", "6"))
LLM_FALLBACK_MOCK = os.getenv("LLM_FALLBACK_MOCK", "1") == "1"

# Sessioni di conversazione
SESSION_TTL_MINUTES = int(os.getenv("SESSION_TTL_MINUTES", "30"))
SESSION_MAX_MESSAGES = int(os.getenv("SESSION_MAX_MESSAGES", "30"))

# Regole di prenotazione
SLOT_DURATION_MINUTES = 120  # quanto "occupa" un tavolo una prenotazione
BOOKING_HORIZON_DAYS = 60  # fino a quanti giorni in avanti si può prenotare
MAX_PARTY_SIZE = 10
