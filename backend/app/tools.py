"""Strumenti (function calling) che l'LLM può invocare e relativo dispatcher."""
from __future__ import annotations

import json
import logging
import sqlite3

from . import services
from .services import BookingError

log = logging.getLogger("backend.tools")

TOOLS = [
    {"type": "function", "function": {
        "name": "get_restaurant_info",
        "description": "Restituisce le informazioni del ristorante: nome, indirizzo, come arrivare, telefono, email, "
                       "orari di apertura, accessibilità, animali, pagamenti, allergie, gruppi.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    }},
    {"type": "function", "function": {
        "name": "get_menu",
        "description": "Restituisce il menu con prezzi, allergeni e caratteristiche (vegetariano, vegano, senza glutine).",
        "parameters": {"type": "object", "properties": {
            "category": {"type": "string",
                         "description": "Categoria opzionale: Antipasti, Primi, Secondi, Dolci, Bevande. Ometti per il menu completo."},
            "diet": {"type": "string", "enum": ["vegetariano", "vegano", "senza glutine"],
                     "description": "Filtro opzionale: restituisce SOLO i piatti adatti. Usalo sempre per domande su "
                                    "piatti vegani, vegetariani o senza glutine (celiachia)."},
        }, "required": []},
    }},
    {"type": "function", "function": {
        "name": "check_availability",
        "description": "Verifica se c'è un tavolo libero per data, ora e numero di persone. Se non c'è propone orari alternativi.",
        "parameters": {"type": "object", "properties": {
            "date": {"type": "string", "description": "Data nel formato AAAA-MM-GG"},
            "time": {"type": "string", "description": "Ora nel formato HH:MM (24 ore)"},
            "party_size": {"type": "integer", "description": "Numero di persone"},
        }, "required": ["date", "time", "party_size"]},
    }},
    {"type": "function", "function": {
        "name": "create_reservation",
        "description": "Crea la prenotazione nel database e restituisce il codice univoco di 6 cifre. Da invocare SOLO quando tutti i dati (data, ora, persone, nome, contatto telefonico valido di almeno 8 cifre) sono stati raccolti e confermati.",
        "parameters": {"type": "object", "properties": {
            "date": {"type": "string", "description": "Data nel formato AAAA-MM-GG"},
            "time": {"type": "string", "description": "Ora nel formato HH:MM (24 ore)"},
            "party_size": {"type": "integer", "description": "Numero di persone"},
            "customer_name": {"type": "string", "description": "Nome del cliente, copiato esattamente (anche se è un segnaposto come [NOME_1A2B3C])"},
            "contact": {"type": "string", "description": "Numero di telefono valido (cellulare o fisso di almeno 8-10 cifre, es. 3401234567) oppure segnaposto privacy [TEL_...]. È severamente vietato inserire numeri fittizi o troppo brevi (es. 123, 456)."},
            "notes": {"type": "string", "description": "Note opzionali: allergie, seggiolone, ricorrenze, preferenze di zona"},
        }, "required": ["date", "time", "party_size", "customer_name", "contact"]},
    }},
    {"type": "function", "function": {
        "name": "get_reservation",
        "description": "Recupera i dettagli di una prenotazione esistente dato il suo codice di 6 cifre.",
        "parameters": {"type": "object", "properties": {
            "code": {"type": "string", "description": "Codice prenotazione di 6 cifre"},
        }, "required": ["code"]},
    }},
    {"type": "function", "function": {
        "name": "modify_reservation",
        "description": "Modifica data, ora, numero di persone o note di una prenotazione esistente. Indica solo i campi da cambiare. "
                       "Da chiamare SOLO dopo conferma esplicita del cliente.",
        "parameters": {"type": "object", "properties": {
            "code": {"type": "string", "description": "Codice prenotazione di 6 cifre"},
            "date": {"type": "string", "description": "Nuova data AAAA-MM-GG (opzionale)"},
            "time": {"type": "string", "description": "Nuova ora HH:MM (opzionale)"},
            "party_size": {"type": "integer", "description": "Nuovo numero di persone (opzionale)"},
            "notes": {"type": "string", "description": "Nuove note (opzionale)"},
        }, "required": ["code"]},
    }},
    {"type": "function", "function": {
        "name": "cancel_reservation",
        "description": "Cancella una prenotazione esistente. Da chiamare SOLO dopo conferma esplicita del cliente.",
        "parameters": {"type": "object", "properties": {
            "code": {"type": "string", "description": "Codice prenotazione di 6 cifre"},
        }, "required": ["code"]},
    }},
]

TOOL_NAMES = {t["function"]["name"] for t in TOOLS}


def _clean(args: dict, key: str):
    """Valori vuoti o 'null' passati dall'LLM vengono trattati come assenti."""
    value = args.get(key)
    if value is None or (isinstance(value, str) and value.strip().lower() in ("", "null", "none")):
        return None
    return value


def execute_tool(conn: sqlite3.Connection, name: str, args: dict, channel: str = "api") -> dict:
    """Esegue uno strumento e restituisce sempre un dict serializzabile (mai eccezioni)."""
    args = args if isinstance(args, dict) else {}
    try:
        if name == "get_restaurant_info":
            result = services.get_info(conn)
        elif name == "get_menu":
            result = services.get_menu(conn, _clean(args, "category"), _clean(args, "diet"))
        elif name == "check_availability":
            result = services.check_availability(conn, args.get("date"), args.get("time"), args.get("party_size"))
        elif name == "create_reservation":
            result = services.create_reservation(
                conn, args.get("date"), args.get("time"), args.get("party_size"),
                customer_name=_clean(args, "customer_name") or "", contact=_clean(args, "contact") or "",
                notes=_clean(args, "notes") or "", channel=channel,
            )
        elif name == "get_reservation":
            result = services.get_reservation(conn, args.get("code"))
        elif name == "modify_reservation":
            result = services.modify_reservation(
                conn, args.get("code"), date_str=_clean(args, "date"), time_str=_clean(args, "time"),
                party_size=_clean(args, "party_size"), notes=_clean(args, "notes"),
            )
        elif name == "cancel_reservation":
            result = services.cancel_reservation(conn, args.get("code"))
        else:
            return {"ok": False, "errore": f"Strumento sconosciuto: {name}"}
        return {"ok": True, "risultato": result}
    except BookingError as exc:
        return {"ok": False, "errore": str(exc)}
    except Exception:  # errore inatteso: lo logghiamo ma non facciamo cadere la conversazione
        log.exception("Errore nello strumento %s", name)
        return {"ok": False, "errore": "Errore interno durante l'operazione. Riprovare più tardi."}


def to_json(result: dict) -> str:
    return json.dumps(result, ensure_ascii=False)
