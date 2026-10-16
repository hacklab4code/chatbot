"""Voice-bot per la prenotazione di un tavolo.

Pipeline (tutto in locale su questa macchina, tranne la chiamata al BE in LAN):
  microfono -> STT (faster-whisper) -> normalizzazione parlato -> pseudonimizzazione
  -> BE (rete) -> re-identificazione -> adattamento per la voce -> TTS (voci di sistema)

Avvio:
  python -m voice_bot.main              conversazione a voce (microfono + altoparlanti)
  python -m voice_bot.main --text       si scrive invece di parlare (la risposta è comunque letta)
  python -m voice_bot.main --no-tts     le risposte vengono solo stampate
  python -m voice_bot.main --wav f.wav  elabora un file audio (utile per test e demo)
"""
from __future__ import annotations

import argparse
import logging
import re
import secrets
import sys

from . import config
from .be_client import BackendClient, BackendError
from .privacy import Pseudonymizer
from .spoken import normalize_transcript, prepare_for_speech

log = logging.getLogger("voice")

GREETING = "Buongiorno, Ristorante Zio Pierino PSG. Desidera prenotare un tavolo o avere informazioni?"
GOODBYE = "Grazie per aver chiamato Zio Pierino. Arrivederci!"
NOT_UNDERSTOOD = "Non ho capito, può ripetere?"
EXIT_WORDS = re.compile(r"^\W*(arrivederci|ciao ciao|basta così|fine|esci|chiudi|addio|buona serata)\W*$", re.I)


class VoiceBot:
    def __init__(self, backend: BackendClient, pseudo: Pseudonymizer, session_id: str | None = None):
        self.backend = backend
        self.pseudo = pseudo
        self.session_id = session_id or secrets.token_hex(16)

    def handle_transcript(self, transcript: str) -> dict:
        """Dal testo riconosciuto alla risposta da pronunciare."""
        text = normalize_transcript(transcript)
        masked, replaced = self.pseudo.pseudonymize(text)
        try:
            reply = self.backend.chat(self.session_id, masked, channel="voice")["reply"]
        except BackendError as exc:
            reply = str(exc)
        reply = self.pseudo.reidentify(reply)
        return {"heard": text, "sent_to_backend": masked, "pseudonymized": [r["type"] for r in replaced],
                "reply": reply, "speech": prepare_for_speech(reply)}

    def close(self) -> None:
        try:
            self.backend.reset(self.session_id)
        except BackendError:
            pass


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Voice-bot Ristorante Zio Pierino PSG")
    parser.add_argument("--text", action="store_true", help="input da tastiera invece che dal microfono")
    parser.add_argument("--no-tts", action="store_true", help="non leggere le risposte ad alta voce")
    parser.add_argument("--wav", nargs="+", help="uno o più file audio da elaborare in sequenza")
    parser.add_argument("--quiet", action="store_true", help="non mostrare cosa viene inviato al server")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    bot = VoiceBot(BackendClient(config.BE_URL, config.BE_API_KEY, config.BE_TIMEOUT),
                   Pseudonymizer.from_dir(config.DATA_DIR, config.PSEUDO_SECRET))
    tts = None
    if not args.no_tts:
        from .tts import TextToSpeech
        tts = TextToSpeech()
    stt = mic = None
    if not args.text:
        print(f"Caricamento del modello di riconoscimento vocale '{config.WHISPER_MODEL}'...")
        from .stt import SpeechToText
        stt = SpeechToText()
    if not args.text and not args.wav:
        from .audio import Microphone
        mic = Microphone()
        print("Calibrazione del microfono: resti in silenzio un secondo...")
        mic.calibrate()

    def speak(text: str) -> None:
        print(f"Bot: {text}\n")
        if tts:
            tts.say(prepare_for_speech(text))

    def turn(transcript: str) -> bool:
        """Gestisce un turno; restituisce False se la conversazione è finita."""
        if not transcript.strip():
            speak(NOT_UNDERSTOOD)
            return True
        if EXIT_WORDS.match(transcript):
            speak(GOODBYE)
            return False
        result = bot.handle_transcript(transcript)
        print(f"Lei: {result['heard']}")
        if result["pseudonymized"] and not args.quiet:
            print(f"  [privacy] inviato al server: {result['sent_to_backend']}")
        print(f"Bot: {result['reply']}\n")
        if tts:
            tts.say(result["speech"])
        return True

    try:
        if args.wav:
            for path in args.wav:
                if not turn(stt.transcribe(path)):
                    break
            return
        speak(GREETING)
        while True:
            if args.text:
                try:
                    transcript = input("Lei (scriva): ")
                except EOFError:
                    break
            else:
                print("In ascolto...")
                audio = mic.listen()
                if audio is None:
                    continue  # nessuno ha parlato: si continua ad ascoltare
                transcript = stt.transcribe(audio)
            if not turn(transcript):
                break
    except KeyboardInterrupt:
        print()
    finally:
        bot.close()


if __name__ == "__main__":
    main()
