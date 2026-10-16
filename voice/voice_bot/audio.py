"""Acquisizione audio dal microfono con rilevamento automatico di inizio/fine frase (VAD a energia)."""
from __future__ import annotations

import queue
import time

import numpy as np

from . import config

BLOCK_SECONDS = 0.03


def _rms(block: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(block, dtype=np.float64)))) if block.size else 0.0


class Microphone:
    def __init__(self, device=config.MIC_DEVICE, sample_rate: int = config.SAMPLE_RATE):
        import sounddevice as sd  # import qui: i test non richiedono una scheda audio
        self._sd = sd
        self.device = int(device) if isinstance(device, str) and device.isdigit() else device
        self.sample_rate = sample_rate
        self.threshold = 0.01

    def calibrate(self, seconds: float = 1.0) -> float:
        """Misura il rumore di fondo e imposta la soglia di voce poco sopra."""
        rec = self._sd.rec(int(seconds * self.sample_rate), samplerate=self.sample_rate, channels=1,
                           dtype="float32", device=self.device)
        self._sd.wait()
        noise = _rms(rec[:, 0])
        self.threshold = max(0.008, noise * 3.0)
        return self.threshold

    def listen(self) -> np.ndarray | None:
        """Attende che l'utente parli e registra fino a una pausa. Restituisce audio mono float32 a 16 kHz."""
        q: queue.Queue = queue.Queue()
        block = int(BLOCK_SECONDS * self.sample_rate)
        pre_roll = int(0.3 / BLOCK_SECONDS)  # conserva 300 ms prima dell'inizio della voce

        def callback(indata, _frames, _time, _status):
            q.put(indata[:, 0].copy())

        chunks, history, speaking = [], [], False
        silence_blocks = 0
        started = time.monotonic()
        with self._sd.InputStream(samplerate=self.sample_rate, channels=1, dtype="float32",
                                  blocksize=block, device=self.device, callback=callback):
            while True:
                data = q.get()
                loud = _rms(data) > self.threshold
                if not speaking:
                    history = (history + [data])[-pre_roll:]
                    if loud:
                        speaking, chunks = True, list(history)
                        speech_started = time.monotonic()
                    elif time.monotonic() - started > config.WAIT_FOR_SPEECH_SECONDS:
                        return None
                    continue
                chunks.append(data)
                silence_blocks = 0 if loud else silence_blocks + 1
                if silence_blocks * BLOCK_SECONDS >= config.SILENCE_SECONDS:
                    break
                if time.monotonic() - speech_started > config.MAX_UTTERANCE_SECONDS:
                    break
        audio = np.concatenate(chunks)
        return audio if audio.size > self.sample_rate * 0.4 else None  # scarta rumori brevissimi
