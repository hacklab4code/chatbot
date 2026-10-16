"""Controllo di sicurezza lato BE (difesa in profondità).

La rimozione dei dati personali è compito di CHAT e VOICE: il BE però non si fida
ciecamente e, se nel testo arrivano ancora dati riconoscibili (email, telefoni,
codici fiscali, IBAN, carte), li oscura prima di passarli all'LLM o salvarli.
"""
import re

_PATTERNS = [
    ("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")),
    ("IBAN", re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]){11,30}\b", re.I)),
    ("CF", re.compile(r"\b[A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z]\b", re.I)),
    ("CARTA", re.compile(r"\b(?:\d[ -]?){13,19}\b")),
    ("TEL", re.compile(r"(?<![\w\]])(?:\+|00)?\d(?:[\s./-]?\d){8,13}\b")),
]


def redact(text: str) -> tuple[str, list[str]]:
    """Restituisce il testo oscurato e l'elenco dei tipi di dato trovati."""
    found = []
    for label, pattern in _PATTERNS:
        text, n = pattern.subn(f"[{label}_OSCURATO]", text)
        if n:
            found.append(label)
    return text, found
