"""Speech-to-text locale con faster-whisper (nessun servizio cloud)."""
import logging
import wave

import numpy as np

from . import config

log = logging.getLogger("voice.stt")

# Suggerisce a Whisper il dominio, migliorando nomi di piatti e parole tipiche
INITIAL_PROMPT = ("Conversazione con un ristorante: prenotazione di un tavolo, menu, orari, "
                  "codice prenotazione, numero di persone, sabato sera alle 20 e 30.")


class SpeechToText:
    def __init__(self, model_size: str = config.WHISPER_MODEL, device: str = config.WHISPER_DEVICE):
        from faster_whisper import WhisperModel
        config.WHISPER_MODELS_DIR.mkdir(parents=True, exist_ok=True)
        try:
            self.model = WhisperModel(model_size, device=device, compute_type="default",
                                      download_root=str(config.WHISPER_MODELS_DIR))
            # Le librerie CUDA (es. cuBLAS) vengono caricate solo alla prima inferenza:
            # una trascrizione di prova su un secondo di silenzio fa emergere subito il problema.
            list(self.model.transcribe(np.zeros(config.SAMPLE_RATE, dtype=np.float32), language=config.LANGUAGE)[0])
        except Exception as exc:  # es. CUDA non disponibile: ripiega sulla CPU
            if device == "cpu":
                raise
            log.warning("Whisper su '%s' non disponibile (%s): uso la CPU", device, exc)
            self.model = WhisperModel(model_size, device="cpu", compute_type="int8",
                                      download_root=str(config.WHISPER_MODELS_DIR))

    def transcribe(self, audio: np.ndarray | str) -> str:
        """Accetta audio float32 mono a 16 kHz oppure il percorso di un file WAV."""
        if isinstance(audio, str):
            audio = load_wav(audio)
        segments, _info = self.model.transcribe(
            audio, language=config.LANGUAGE, beam_size=5, vad_filter=True,
            initial_prompt=INITIAL_PROMPT, condition_on_previous_text=False,
        )
        return " ".join(s.text.strip() for s in segments).strip()


def load_wav(path: str, target_rate: int = config.SAMPLE_RATE) -> np.ndarray:
    """Legge un WAV PCM (8/16/32 bit, mono o stereo) e lo converte in float32 mono a 16 kHz.

    Lo facciamo noi, con la libreria standard, invece di delegare il decoding a
    faster-whisper/PyAV: una dipendenza nativa in meno da tenere allineata.
    """
    with wave.open(path, "rb") as w:
        width, channels, rate = w.getsampwidth(), w.getnchannels(), w.getframerate()
        raw = w.readframes(w.getnframes())
    if width == 1:
        data = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128) / 128
    elif width == 2:
        data = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768
    elif width == 4:
        data = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648
    else:
        raise ValueError(f"WAV a {width * 8} bit non supportato")
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)
    if rate != target_rate and data.size:
        n = int(round(data.size * target_rate / rate))
        data = np.interp(np.linspace(0, data.size - 1, n), np.arange(data.size), data).astype(np.float32)
    return data
