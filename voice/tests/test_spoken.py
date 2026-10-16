import pytest

from voice_bot.main import VoiceBot
from voice_bot.privacy import Pseudonymizer
from voice_bot.spoken import normalize_transcript, prepare_for_speech


@pytest.mark.parametrize("heard,expected", [
    ("il mio numero è tre quattro sette uno due tre quattro cinque sei sette",
     "il mio numero è 3471234567"),
    ("il codice è sette uno sei quattro uno zero.", "il codice è 716410."),
    ("il codice è 7 1 6 4 1 0", "il codice è 716410"),
    ("siamo in sei persone alle otto", "siamo in sei persone alle otto"),
    ("tavolo per due domani alle 20", "tavolo per due domani alle 20"),
    ("la mail è giulia punto verdi chiocciola gmail punto com grazie",
     "la mail è giulia.verdi@gmail.com grazie"),
    ("il numero è 347 123 4567", "il numero è 347 123 4567"),
])
def test_normalize_transcript(heard, expected):
    assert normalize_transcript(heard) == expected


def test_prepare_for_speech():
    text = ("La sua prenotazione è confermata!\n\n**Dettagli:**\n- **Data:** 2026-10-15\n- Ora: 20:30\n"
            "- Codice: **716410**\n- Prezzo: 14,00 €")
    out = prepare_for_speech(text)
    assert "*" not in out and "-" not in out
    assert "15 ottobre 2026" in out and "20 e 30" in out and "7 1 6 4 1 0" in out and "14 euro" in out
    assert prepare_for_speech("alle 20:00 del 1/11") == "alle 20 del primo novembre."


class FakeBackend:
    def __init__(self):
        self.sent = []

    def chat(self, session_id, message, channel):
        self.sent.append((message, channel))
        token = message.split("a nome ")[1].split(",")[0]
        return {"reply": f"Confermo per **{token}** alle 20:30, codice 123456."}

    def reset(self, session_id):
        return {}


def test_pipeline_never_sends_personal_data(tmp_path):
    backend = FakeBackend()
    bot = VoiceBot(backend, Pseudonymizer(tmp_path / "v.json", b"k"))
    out = bot.handle_transcript("prenoto a nome Mario Rossi, telefono tre tre tre uno due tre quattro cinque sei sette")
    sent, channel = backend.sent[0]
    assert channel == "voice"
    assert "Mario" not in sent and "Rossi" not in sent and "333" not in sent and "[TEL_" in sent
    assert out["reply"] == "Confermo per **Mario Rossi** alle 20:30, codice 123456."
    assert out["speech"] == "Confermo per Mario Rossi alle 20 e 30, codice 1 2 3 4 5 6."
