"""Adattamenti tra lingua parlata e testo scritto.

- normalize_transcript: ripulisce il testo riconosciuto dallo STT prima della
  pseudonimizzazione (es. "mario punto rossi chiocciola gmail punto com" diventa
  un indirizzo email riconoscibile, le cifre dettate a parole diventano numeri).
- prepare_for_speech: rende la risposta del BE adatta alla lettura ad alta voce
  (niente markdown, orari, date, prezzi e codici pronunciabili).
"""
from __future__ import annotations

import re

DIGIT_WORDS = {"zero": "0", "uno": "1", "due": "2", "tre": "3", "quattro": "4", "cinque": "5",
               "sei": "6", "sette": "7", "otto": "8", "nove": "9"}
MONTHS = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto",
          "settembre", "ottobre", "novembre", "dicembre"]

def _join_digit_sequences(text: str) -> str:
    """'tre quattro sette uno due tre ...' -> '347123...' (solo sequenze di almeno 6 cifre)."""
    tokens = re.split(r"(\s+)", text)
    out, run = [], []

    def flush():
        words = [t for t in run if not t.isspace()]
        digits = "".join(DIGIT_WORDS.get(w.lower().strip(",."), w.strip(",.")) for w in words)
        spoken = any(w.lower().strip(",.") in DIGIT_WORDS for w in words)
        single = all(len(w.strip(",.")) == 1 for w in words)
        if len(digits) >= 6 and (spoken or single):
            trailing = run[-1][-1] if run and run[-1][-1] in ",." else ""
            out.append(digits + trailing)
        else:
            out.extend(run)
        run.clear()

    for tok in tokens:
        core = tok.lower().strip(",.")
        if tok.isspace():
            (run if run else out).append(tok)
        elif core in DIGIT_WORDS or (core.isdigit() and tok.strip(",.") == core):
            run.append(tok)
        else:
            # gli spazi finali della sequenza non vanno inglobati
            trailing_ws = []
            while run and run[-1].isspace():
                trailing_ws.insert(0, run.pop())
            if run:
                flush()
            out.extend(trailing_ws)
            out.append(tok)
    trailing_ws = []
    while run and run[-1].isspace():
        trailing_ws.insert(0, run.pop())
    if run:
        flush()
    out.extend(trailing_ws)
    return "".join(out)


def _spoken_email(text: str) -> str:
    text = re.sub(r"\s*\b(?:chiocciola|chiocciolina)\b\s*", "@", text, flags=re.I)

    def fix(m: re.Match) -> str:
        return re.sub(r"\s+(?:punto|dot)\s+", ".", m.group(0), flags=re.I).replace(" ", "")

    word = r"[\w-]+"
    return re.sub(rf"{word}(?:\s+(?:punto|dot)\s+{word})*@{word}(?:\s+(?:punto|dot)\s+{word})+", fix, text, flags=re.I)


def normalize_transcript(text: str) -> str:
    text = " ".join(text.split())
    text = _spoken_email(text)
    text = _join_digit_sequences(text)
    return text


# ------------------------------------------------------------------ uscita vocale

def _say_time(m: re.Match) -> str:
    h, mm = int(m.group(1)), m.group(2)
    return f"{h}" if mm == "00" else f"{h} e {int(mm)}"


def _say_date(day: str, month: str, year: str | None) -> str:
    d, mo = int(day), int(month)
    if not (1 <= mo <= 12 and 1 <= d <= 31):
        return f"{day}/{month}" + (f"/{year}" if year else "")
    return f"{'primo' if d == 1 else d} {MONTHS[mo - 1]}" + (f" {year}" if year else "")


def prepare_for_speech(text: str) -> str:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    text = re.sub(r"(?:call:)?(?:create_reservation|check_availability|get_reservation|modify_reservation|cancel_reservation|get_menu|get_restaurant_info)\b[^\n]*\(?\{[\s\S]*?\}\)?", "", text, flags=re.I)
    text = re.sub(r"(?:call:)?(?:create_reservation|check_availability|get_reservation|modify_reservation|cancel_reservation|get_menu|get_restaurant_info)\b", "", text, flags=re.I)
    text = re.sub(r'\{[^{}]*"(?:customer_name|party_size|date|time|contact|code)"[^{}]*\}', "", text, flags=re.I)
    text = re.sub(r"```(?:json|python)?[\s\S]*?```", "", text)
    text = re.sub(r"</?[a-z_]+>", "", text)
    text = re.sub(r"[*_#`>]+", "", text)                         # markdown
    text = re.sub(r"^\s*(?:[-•]|\d+\.)\s+", "", text, flags=re.M)  # elenchi
    text = re.sub(r"[\U0001F000-\U0001FFFF☀-➿]", "", text)  # emoji
    text = re.sub(r"(\d+),00\s*€", r"\1 euro", text)
    text = re.sub(r"(\d+)[,.](\d{2})\s*€", r"\1 euro e \2", text)
    text = re.sub(r"€\s*(\d+)", r"\1 euro", text).replace("€", "euro")
    text = re.sub(r"\b(\d{4})-(\d{2})-(\d{2})\b", lambda m: _say_date(m.group(3), m.group(2), m.group(1)), text)
    text = re.sub(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{4}))?\b", lambda m: _say_date(m.group(1), m.group(2), m.group(3)), text)
    text = re.sub(r"\b([01]?\d|2[0-3])[:.]([0-5]\d)\b", _say_time, text)
    text = re.sub(r"(?<![\d+])\b(\d{6})\b(?!\d)", lambda m: " ".join(m.group(1)), text)  # codice prenotazione
    # ogni riga diventa una frase: la sintesi vocale fa una pausa tra le voci di un elenco
    lines = [ln.strip().rstrip(":").strip() for ln in text.splitlines() if ln.strip().rstrip(":").strip()]
    text = " ".join(ln if ln.endswith((".", "?", "!")) else ln + "." for ln in lines)
    text = re.sub(r"\s+([.,;:?!])", r"\1", text)
    text = re.sub(r"([?!])\.", r"\1", text)
    return re.sub(r"\s{2,}", " ", text).strip()
