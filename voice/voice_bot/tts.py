"""Text-to-speech locale con le voci di sistema (pyttsx3: SAPI5 / NSSpeech / eSpeak)."""
from __future__ import annotations

import logging

from . import config

log = logging.getLogger("voice.tts")


class TextToSpeech:
    def __init__(self, voice_hint: str = config.TTS_VOICE, rate: int = config.TTS_RATE):
        import pyttsx3
        self._pyttsx3 = pyttsx3
        self.rate = rate
        self.voice_id = self._pick_voice(voice_hint)

    def _pick_voice(self, hint: str) -> str | None:
        engine = self._pyttsx3.init()
        voices = engine.getProperty("voices")
        engine.stop()

        def text(v):
            return f"{v.name} {v.id} {' '.join(map(str, v.languages or []))}".lower()

        for v in voices:
            if hint and hint.lower() in text(v):
                return v.id
        for v in voices:
            if any(k in text(v) for k in ("italian", "ital", "it-it", "it_it")):
                return v.id
        log.warning("Nessuna voce italiana installata: uso la voce predefinita del sistema")
        return None

    def _engine(self):
        # Un motore nuovo per ogni frase: evita il blocco noto di runAndWait() su Windows
        engine = self._pyttsx3.init()
        engine.setProperty("rate", self.rate)
        if self.voice_id:
            engine.setProperty("voice", self.voice_id)
        return engine

    def say(self, text: str) -> None:
        engine = self._engine()
        engine.say(text)
        engine.runAndWait()
        engine.stop()

    def save(self, text: str, path: str) -> None:
        engine = self._engine()
        engine.save_to_file(text, path)
        engine.runAndWait()
        engine.stop()
