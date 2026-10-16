"""Chat-bot da terminale (alternativa all'interfaccia web). Avvio: python -m chat_app.cli"""
import secrets
import sys

from . import config
from .be_client import BackendClient, BackendError
from .privacy import Pseudonymizer


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    backend = BackendClient(config.BE_URL, config.BE_API_KEY, config.BE_TIMEOUT)
    pseudo = Pseudonymizer.from_dir(config.DATA_DIR, config.PSEUDO_SECRET)
    session_id = secrets.token_hex(16)
    print("Ristorante Zio Pierino PSG - assistente prenotazioni (scriva 'esci' per uscire)\n")
    while True:
        try:
            text = input("Lei: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not text:
            continue
        if text.lower() in ("esci", "exit", "quit"):
            break
        masked, replaced = pseudo.pseudonymize(text)
        if replaced:
            print(f"  [privacy] inviato al server: {masked}")
        try:
            reply = backend.chat(session_id, masked, channel="chat")["reply"]
        except BackendError as exc:
            print(f"  [errore] {exc}")
            continue
        print(f"Bot: {pseudo.reidentify(reply)}\n")
    try:
        backend.reset(session_id)
    except BackendError:
        pass
    print("Arrivederci!")


if __name__ == "__main__":
    main()
