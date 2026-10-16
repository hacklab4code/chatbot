"""Pseudonimizzazione dei dati personali PRIMA dell'invio al backend.

Ogni dato personale trovato nel testo (nome, telefono, email, codice fiscale,
IBAN, carta di pagamento) viene sostituito da un segnaposto deterministico,
ad esempio "Mario Rossi" -> "[NOME_3FA9C1]".

- Il segnaposto è un HMAC con chiave segreta locale: il BE non può risalire al dato.
- La corrispondenza segnaposto -> dato reale resta SOLO su questa macchina
  (file "vault" locale) e serve a re-identificare le risposte per l'utente.
- Stesso dato => stesso segnaposto, così il BE può riconoscere lo stesso cliente
  tra sessioni diverse senza conoscerne l'identità.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import threading
from pathlib import Path

TOKEN_RE = re.compile(r"\[?\b(NOME|TEL|EMAIL|CF|IBAN|CARTA)_([0-9A-F]{6})\b\]?")

EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]){11,30}\b", re.I)
CF_RE = re.compile(r"\b[A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z]\b", re.I)
CARD_RE = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")
# Telefono: 9-13 cifre con separatori spazio/punto/trattino, prefisso internazionale opzionale.
# Lo slash non è ammesso per non confondere le date (17/10/2026).
PHONE_RE = re.compile(r"(?<![\w\[])(?:\+|00)?\d(?:[ .-]?\d){8,12}(?!\d)")
DATE_RE = re.compile(r"(?<!\d)\d{1,2}[.-]\d{1,2}[.-]\d{2,4}(?!\d)")

WORD = r"[A-Za-zÀ-ÖØ-öø-ÿ'’]+"
# Frasi che introducono un nome: dopo di esse si prendono fino a 3 parole "da nome".
NAME_TRIGGERS = re.compile(
    r"\b(mi chiamo|il mio nome (?:è|e'|é|e)|a nome(?: di)?|intestat[ao] a|cognome(?: è)?|"
    r"nome(?: è)?:?|per conto di|sono il signor|sono la signora|signor|signora|sig\.ra|sig\.)\s+",
    re.I,
)
# Dopo "sono" solo se la parola è maiuscola (es. "Sono Giulia") o un nome noto.
SONO_TRIGGER = re.compile(r"\b(?:sono|qui è|qui e')\s+", re.I)

STOPWORDS = {
    "a", "ad", "al", "alla", "alle", "allo", "ai", "agli", "il", "lo", "la", "i", "gli", "le", "un", "uno", "una",
    "di", "da", "del", "della", "dei", "delle", "in", "con", "su", "per", "tra", "fra", "e", "ed", "o", "ma",
    "che", "chi", "non", "si", "sì", "no", "ok", "mi", "ti", "ci", "vi", "ne", "io", "noi", "voi", "lei", "lui",
    "mio", "mia", "suo", "sua", "è", "e'", "sono", "siamo", "ho", "abbiamo", "vorrei", "voglio", "volevo",
    "prenotare", "prenotazione", "tavolo", "posto", "posti", "persone", "persona", "numero", "telefono",
    "cellulare", "mail", "email", "contatto", "recapito", "grazie", "ciao", "salve", "buongiorno", "buonasera",
    "oggi", "domani", "dopodomani", "stasera", "stamattina", "pranzo", "cena", "sera", "ore", "orario",
    "lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica", "lunedi", "martedi",
    "mercoledi", "giovedi", "venerdi", "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio",
    "agosto", "settembre", "ottobre", "novembre", "dicembre", "due", "tre", "quattro", "cinque", "sei", "sette",
    "otto", "nove", "dieci", "celiaco", "celiaca", "allergico", "allergica", "vegetariano", "vegano", "anche",
    "invece", "poi", "allora", "quindi", "comunque", "bene", "perfetto", "confermo", "certo", "esatto",
    "interessato", "interessata", "qui", "qua", "ancora", "già", "solo", "sempre", "tutti", "tutte",
    "signor", "signora", "dottor", "dottoressa", "famiglia", "chiamo", "nome", "cognome",
}

# Nomi propri italiani comuni (esclusi quelli ambigui con parole comuni, es. "Rosa", "Serena", "Bianca").
FIRST_NAMES = set("""
alessandro alessandra alberto alice andrea angela anna antonio antonella arianna aurora beatrice benedetta
carlo carla caterina chiara claudio claudia cristina cristian daniele daniela davide debora diego domenico
edoardo elena elisa elisabetta emanuele emma enrico enrica eleonora fabio fabrizio federico federica
filippo francesco francesca franco gabriele gabriella giacomo giada giorgio giorgia giovanni giovanna giulio
giulia giuseppe giuseppina greta guido ilaria irene jacopo laura leonardo lorenzo lorenza luca lucia luigi
luisa manuela marco marcella maria mario marta martina massimo matteo mattia michele michela monica nicola
nicoletta noemi paolo paola patrizia pietro raffaele riccardo roberto roberta rocco salvatore sara silvia
simone simona sofia stefano stefania teresa tommaso valentina valerio veronica vincenzo vittoria ginevra
camilla giorgio samuele gaia nadia ludovica rebecca elia samuel christian denis ivan alex
""".split())

LABELS = ("NOME", "TEL", "EMAIL", "CF", "IBAN", "CARTA")


def _luhn_ok(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d = d * 2 - 9 if d * 2 > 9 else d * 2
        total, alt = total + d, not alt
    return total % 10 == 0


def _is_name_word(word: str, need_capital: bool) -> bool:
    w = word.strip("'’")
    if len(w) < 2 or w.lower() in STOPWORDS:
        return False
    return (w[0].isupper() or w.lower() in FIRST_NAMES) if need_capital else True


def _name_spans(text: str) -> list[tuple[int, int]]:
    """Trova le porzioni di testo che sono nomi di persona."""
    spans = []

    def take_words(start: int, first_needs_capital: bool, others_need_capital: bool, max_words: int = 3):
        end, count = start, 0
        for m in re.finditer(rf"\s*({WORD})", text[start:]):
            if m.start() != end - start:  # le parole devono essere consecutive
                break
            word = m.group(1)
            if not _is_name_word(word, first_needs_capital if count == 0 else others_need_capital):
                break
            end = start + m.end()
            count += 1
            if count >= max_words:
                break
        return (start, end) if count else None

    for m in NAME_TRIGGERS.finditer(text):
        span = take_words(m.end(), first_needs_capital=False, others_need_capital=False)
        if span:
            spans.append(span)
    for m in SONO_TRIGGER.finditer(text):
        span = take_words(m.end(), first_needs_capital=True, others_need_capital=True)
        if span:
            spans.append(span)
    # nomi propri noti in qualsiasi punto, con cognome opzionale se maiuscolo
    for m in re.finditer(rf"\b{WORD}\b", text):
        word = m.group(0)
        if word.lower() in FIRST_NAMES and word[0].isupper():
            span = take_words(m.start(), first_needs_capital=True, others_need_capital=True, max_words=3)
            if span:
                spans.append(span)
    return spans


def _merge(spans: list[tuple[int, int, str]]) -> list[tuple[int, int, str]]:
    """Unisce gli intervalli sovrapposti (vince il primo trovato, cioè il più specifico)."""
    result: list[tuple[int, int, str]] = []
    for s in sorted(spans, key=lambda x: (x[0], -(x[1] - x[0]))):
        if result and s[0] < result[-1][1]:
            last = result[-1]
            if s[2] == last[2]:
                result[-1] = (last[0], max(last[1], s[1]), last[2])
            continue
        result.append(s)
    return result


def find_personal_data(text: str) -> list[tuple[int, int, str]]:
    """Restituisce gli intervalli (inizio, fine, tipo) dei dati personali nel testo."""
    found = []
    protected = [(m.start(), m.end()) for m in TOKEN_RE.finditer(text)]  # segnaposto già presenti

    def free(a, b):
        return not any(a < pe and b > ps for ps, pe in protected + [(x[0], x[1]) for x in found])

    for label, regex in (("EMAIL", EMAIL_RE), ("IBAN", IBAN_RE), ("CF", CF_RE)):
        for m in regex.finditer(text):
            if free(m.start(), m.end()):
                found.append((m.start(), m.end(), label))
    for m in CARD_RE.finditer(text):
        digits = re.sub(r"\D", "", m.group(0))
        if 13 <= len(digits) <= 19 and _luhn_ok(digits) and free(m.start(), m.end()):
            found.append((m.start(), m.end(), "CARTA"))
    for m in PHONE_RE.finditer(text):
        if DATE_RE.search(m.group(0)):  # "17.10.2026 20.30" è una data, non un telefono
            continue
        if free(m.start(), m.end()):
            found.append((m.start(), m.end(), "TEL"))
    for a, b in _name_spans(text):
        if free(a, b):
            found.append((a, b, "NOME"))
    return _merge(found)


class Pseudonymizer:
    def __init__(self, vault_path: Path, secret: bytes):
        self.vault_path = Path(vault_path)
        self._secret = secret
        self._lock = threading.Lock()
        self._vault: dict[str, str] = {}
        if self.vault_path.exists():
            self._vault = json.loads(self.vault_path.read_text(encoding="utf-8"))

    @classmethod
    def from_dir(cls, data_dir: Path, secret: str = "") -> "Pseudonymizer":
        """Usa la chiave passata o ne genera/legge una persistente in data_dir/secret.key."""
        data_dir = Path(data_dir)
        data_dir.mkdir(parents=True, exist_ok=True)
        if not secret:
            key_file = data_dir / "secret.key"
            if not key_file.exists():
                key_file.write_text(secrets.token_hex(32), encoding="utf-8")
            secret = key_file.read_text(encoding="utf-8").strip()
        return cls(data_dir / "vault.json", secret.encode())

    def _token(self, label: str, value: str) -> str:
        norm = re.sub(r"[\s.\-]", "", value).lower() if label != "NOME" else " ".join(value.lower().split())
        if label == "TEL":
            norm = re.sub(r"^(\+|00)39", "", norm)
        digest = hmac.new(self._secret, f"{label}:{norm}".encode(), hashlib.sha256).hexdigest()
        return f"[{label}_{digest[:6].upper()}]"

    def pseudonymize(self, text: str) -> tuple[str, list[dict]]:
        """Restituisce (testo pseudonimizzato, elenco sostituzioni fatte)."""
        spans = find_personal_data(text)
        if not spans:
            return text, []
        out, last, replaced, new_entries = [], 0, [], {}
        for start, end, label in spans:
            original = text[start:end].strip()
            token = self._token(label, original)
            if token not in self._vault:
                new_entries[token] = original
            out += [text[last:start], token]
            last = end
            replaced.append({"type": label, "token": token})
        out.append(text[last:])
        if new_entries:
            with self._lock:
                self._vault.update(new_entries)
                self.vault_path.write_text(json.dumps(self._vault, ensure_ascii=False, indent=1), encoding="utf-8")
        return "".join(out), replaced

    def reidentify(self, text: str) -> str:
        """Rimette i dati reali al posto dei segnaposto (solo per mostrarli all'utente locale)."""
        def sub(m: re.Match) -> str:
            return self._vault.get(f"[{m.group(1)}_{m.group(2)}]", m.group(0))
        return TOKEN_RE.sub(sub, text)
