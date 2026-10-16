"""Logica di business: disponibilità, prenotazioni, menu e informazioni.

Tutte le regole sono qui, in codice deterministico: l'LLM decide *cosa* fare,
ma è questo modulo a validare i dati e a leggere/scrivere sul database.
"""
from __future__ import annotations

import json
import re
import secrets
import sqlite3
from datetime import date, datetime, timedelta

from . import config
from .db import CLOSED_WEEKDAYS, SERVICES, transaction

WEEKDAYS_IT = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
MAX_TABLE_WASTE = 4  # posti vuoti massimi accettati assegnando un tavolo


class BookingError(Exception):
    """Errore di validazione con messaggio in italiano, mostrabile all'utente."""


# ---------------------------------------------------------------- parsing

def parse_date(value: str) -> date:
    value = str(value or "").strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y"):
        try:
            d = datetime.strptime(value, fmt).date()
            # Se l'LLM ha generato un anno passato (es. 2023 o 2024 per abitudine dei pesi),
            # ma l'anno corrente è 2026, correggiamo l'anno all'anno corrente
            now_year = datetime.now().year
            if d.year < now_year:
                try:
                    d = d.replace(year=now_year)
                except ValueError:
                    pass
            return d
        except ValueError:
            pass
    raise BookingError(f"Data non valida: '{value}'. Usa il formato AAAA-MM-GG.")



def parse_time(value: str) -> str:
    raw = str(value or "").strip().lower().replace(".", ":").replace(",", ":")
    raw = raw.removesuffix(" circa").removeprefix("ore ").strip()
    try:
        if ":" in raw:
            h, m = raw.split(":", 1)
            hour, minute = int(h), int(m)
        else:
            hour, minute = int(raw), 0
    except ValueError:
        raise BookingError(f"Orario non valido: '{value}'. Usa il formato HH:MM.") from None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise BookingError(f"Orario non valido: '{value}'.")
    return f"{hour:02d}:{minute:02d}"


def parse_party_size(value) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise BookingError(f"Numero di persone non valido: '{value}'.") from None
    if n < 1:
        raise BookingError("Il numero di persone deve essere almeno 1.")
    if n > config.MAX_PARTY_SIZE:
        raise BookingError(
            f"Online si possono prenotare al massimo {config.MAX_PARTY_SIZE} persone: "
            "per gruppi più numerosi bisogna contattare il ristorante per telefono."
        )
    return n


def normalize_code(code: str) -> str:
    return "".join(ch for ch in str(code or "") if ch.isalnum()).upper()


def validate_phone(contact: str, required: bool = True) -> str:
    raw = str(contact or "").strip()
    if not raw:
        if required:
            raise BookingError("Serve un recapito telefonico di contatto valido (cellulare o fisso) per confermare la prenotazione.")
        return ""
    # Segnaposto di pseudonimizzazione privacy valido es. [TEL_1A2B3C] o [TEL_OSCURATO] (6 caratteri esadecimali)
    if re.fullmatch(r"\[TEL_([0-9A-Fa-f]{6}|OSCURATO)\]", raw):
        return raw
    # Verifica numero di telefono reale: almeno 8 e massimo 15 cifre
    digits = re.sub(r"\D", "", raw)
    if len(digits) < 8 or len(digits) > 15:
        raise BookingError(
            f"Il recapito telefonico '{raw}' non è valido. "
            "Inserire un numero di telefono corretto (almeno 8-10 cifre, cellulare o fisso)."
        )
    return raw


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def describe_date(d: date) -> str:
    return f"{WEEKDAYS_IT[d.weekday()]} {d.strftime('%d/%m/%Y')}"


# ---------------------------------------------------------------- validazione

def validate_slot(d: date, hhmm: str, now: datetime | None = None) -> None:
    now = now or datetime.now()
    if d.weekday() in CLOSED_WEEKDAYS:
        raise BookingError(f"Il ristorante è chiuso il lunedì ({describe_date(d)}).")
    if d < now.date():
        raise BookingError(f"La data {describe_date(d)} è già passata.")
    if d > now.date() + timedelta(days=config.BOOKING_HORIZON_DAYS):
        raise BookingError(f"Si può prenotare al massimo {config.BOOKING_HORIZON_DAYS} giorni in anticipo.")
    t = _minutes(hhmm)
    if not any(_minutes(a) <= t <= _minutes(b) for a, b in SERVICES.values()):
        windows = ", ".join(f"{k} {a}-{b}" for k, (a, b) in SERVICES.items())
        raise BookingError(f"Orario {hhmm} non prenotabile. Orari di prenotazione: {windows}.")
    if datetime.combine(d, datetime.strptime(hhmm, "%H:%M").time()) <= now:
        raise BookingError(f"L'orario {hhmm} di {describe_date(d)} è già passato.")


# ---------------------------------------------------------------- disponibilità

def _find_free_table(conn: sqlite3.Connection, d: date, hhmm: str, party: int,
                     exclude_reservation_id: int | None = None) -> sqlite3.Row | None:
    t = _minutes(hhmm)
    busy = set()
    rows = conn.execute(
        "SELECT id, table_id, time FROM reservations WHERE date = ? AND status = 'confermata'",
        (d.isoformat(),),
    ).fetchall()
    for r in rows:
        if r["id"] != exclude_reservation_id and abs(_minutes(r["time"]) - t) < config.SLOT_DURATION_MINUTES:
            busy.add(r["table_id"])
    candidates = conn.execute(
        "SELECT * FROM restaurant_tables WHERE seats >= ? AND seats - ? <= ? ORDER BY seats, id",
        (party, party, MAX_TABLE_WASTE),
    ).fetchall()
    return next((tbl for tbl in candidates if tbl["id"] not in busy), None)


def _alternatives(conn, d: date, hhmm: str, party: int, now: datetime | None, limit: int = 4) -> list[str]:
    """Orari alternativi liberi nello stesso giorno, ordinati per vicinanza."""
    slots = []
    for start, end in SERVICES.values():
        m = _minutes(start)
        while m <= _minutes(end):
            slots.append(f"{m // 60:02d}:{m % 60:02d}")
            m += 30
    target = _minutes(hhmm)
    free = []
    for s in sorted(slots, key=lambda s: abs(_minutes(s) - target)):
        if s == hhmm:
            continue
        try:
            validate_slot(d, s, now)
        except BookingError:
            continue
        if _find_free_table(conn, d, s, party):
            free.append(s)
        if len(free) >= limit:
            break
    return sorted(free)


def check_availability(conn, date_str: str, time_str: str, party_size, now: datetime | None = None) -> dict:
    d, hhmm, party = parse_date(date_str), parse_time(time_str), parse_party_size(party_size)
    validate_slot(d, hhmm, now)
    table = _find_free_table(conn, d, hhmm, party)
    result = {"data": d.isoformat(), "giorno": describe_date(d), "ora": hhmm, "persone": party,
              "disponibile": table is not None}
    if table is None:
        result["orari_alternativi_stesso_giorno"] = _alternatives(conn, d, hhmm, party, now)
    else:
        result["zona"] = table["area"]
    return result


# ---------------------------------------------------------------- prenotazioni

def _new_code(conn) -> str:
    while True:
        code = f"{secrets.randbelow(900000) + 100000}"  # 6 cifre: facili da dettare a voce
        if not conn.execute("SELECT 1 FROM reservations WHERE code = ?", (code,)).fetchone():
            return code


def _reservation_view(conn, row: sqlite3.Row) -> dict:
    table = conn.execute("SELECT * FROM restaurant_tables WHERE id = ?", (row["table_id"],)).fetchone()
    d = date.fromisoformat(row["date"])
    return {
        "codice": row["code"], "stato": row["status"], "data": row["date"], "giorno": describe_date(d),
        "ora": row["time"], "persone": row["party_size"], "zona": table["area"], "tavolo": table["name"],
        "nome": row["customer_alias"], "contatto": row["contact_alias"], "note": row["notes"] or "",
    }


def _get_row(conn, code: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM reservations WHERE code = ?", (normalize_code(code),)).fetchone()
    if row is None:
        raise BookingError(f"Nessuna prenotazione trovata con il codice '{code}'.")
    return row


def create_reservation(conn, date_str: str, time_str: str, party_size, customer_name: str = "",
                       contact: str = "", notes: str = "", channel: str = "api",
                       now: datetime | None = None) -> dict:
    d, hhmm, party = parse_date(date_str), parse_time(time_str), parse_party_size(party_size)
    validate_slot(d, hhmm, now)
    if not str(customer_name or "").strip():
        raise BookingError("Serve un nome per la prenotazione.")
    valid_contact = validate_phone(contact, required=(channel in ("chat", "voice") or bool(contact)))
    with transaction(conn):
        table = _find_free_table(conn, d, hhmm, party)
        if table is None:
            alt = _alternatives(conn, d, hhmm, party, now)
            raise BookingError(
                f"Nessun tavolo libero per {party} persone {describe_date(d)} alle {hhmm}."
                + (f" Orari liberi lo stesso giorno: {', '.join(alt)}." if alt else " Il giorno è al completo.")
            )
        code = _new_code(conn)
        conn.execute(
            "INSERT INTO reservations(code, date, time, party_size, table_id, customer_alias, contact_alias, notes, channel)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (code, d.isoformat(), hhmm, party, table["id"], str(customer_name).strip(),
             valid_contact, str(notes or "").strip(), channel),
        )
    return _reservation_view(conn, _get_row(conn, code))


def get_reservation(conn, code: str) -> dict:
    return _reservation_view(conn, _get_row(conn, code))


def _ensure_editable(row: sqlite3.Row, now: datetime | None) -> None:
    if row["status"] != "confermata":
        raise BookingError(f"La prenotazione {row['code']} è già stata cancellata.")
    start = datetime.fromisoformat(f"{row['date']}T{row['time']}")
    if start <= (now or datetime.now()):
        raise BookingError(f"La prenotazione {row['code']} è già passata e non può essere modificata.")


def modify_reservation(conn, code: str, date_str: str | None = None, time_str: str | None = None,
                       party_size=None, notes: str | None = None, now: datetime | None = None) -> dict:
    with transaction(conn):
        row = _get_row(conn, code)
        _ensure_editable(row, now)
        d = parse_date(date_str) if date_str else date.fromisoformat(row["date"])
        hhmm = parse_time(time_str) if time_str else row["time"]
        party = parse_party_size(party_size) if party_size not in (None, "") else row["party_size"]
        new_notes = row["notes"] if notes is None else str(notes).strip()
        if (d.isoformat(), hhmm, party, new_notes) == (row["date"], row["time"], row["party_size"], row["notes"]):
            raise BookingError("Non è stata indicata nessuna modifica.")
        validate_slot(d, hhmm, now)
        table = _find_free_table(conn, d, hhmm, party, exclude_reservation_id=row["id"])
        if table is None:
            alt = _alternatives(conn, d, hhmm, party, now)
            raise BookingError(
                f"Nessun tavolo libero per {party} persone {describe_date(d)} alle {hhmm}; "
                "la prenotazione originale resta invariata."
                + (f" Orari liberi lo stesso giorno: {', '.join(alt)}." if alt else "")
            )
        conn.execute(
            "UPDATE reservations SET date = ?, time = ?, party_size = ?, table_id = ?, notes = ?,"
            " updated_at = datetime('now', 'localtime') WHERE id = ?",
            (d.isoformat(), hhmm, party, table["id"], new_notes, row["id"]),
        )
    return _reservation_view(conn, _get_row(conn, code))


def cancel_reservation(conn, code: str, now: datetime | None = None) -> dict:
    with transaction(conn):
        row = _get_row(conn, code)
        _ensure_editable(row, now)
        conn.execute(
            "UPDATE reservations SET status = 'cancellata', updated_at = datetime('now', 'localtime') WHERE id = ?",
            (row["id"],),
        )
    return _reservation_view(conn, _get_row(conn, code))


def list_reservations(conn, date_str: str | None = None) -> list[dict]:
    if date_str:
        rows = conn.execute("SELECT * FROM reservations WHERE date = ? ORDER BY time",
                            (parse_date(date_str).isoformat(),)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM reservations ORDER BY date, time").fetchall()
    return [_reservation_view(conn, r) for r in rows]


# ---------------------------------------------------------------- menu e info

DIETS = {"vegetariano": "vegetarian", "vegano": "vegan", "senza glutine": "gluten_free"}


def get_menu(conn, category: str | None = None, diet: str | None = None) -> dict:
    where, args = [], []
    if category:
        cats = [r[0] for r in conn.execute("SELECT DISTINCT category FROM menu_items ORDER BY id")]
        if category.strip().lower() not in (c.lower() for c in cats):
            raise BookingError(f"Categoria '{category}' inesistente. Categorie disponibili: {', '.join(cats)}.")
        where.append("lower(category) = lower(?)")
        args.append(category.strip())
    if diet:
        key = diet.strip().lower()
        key = {"celiaco": "senza glutine", "vegana": "vegano", "vegetariana": "vegetariano"}.get(key, key)
        if key not in DIETS:
            raise BookingError(f"Filtro '{diet}' non valido. Filtri disponibili: {', '.join(DIETS)}.")
        where.append(f"{DIETS[key]} = 1")  # nome di colonna da whitelist, non da input
    sql = "SELECT * FROM menu_items" + (" WHERE " + " AND ".join(where) if where else "")
    rows = conn.execute(sql + " ORDER BY id", args).fetchall()
    menu: dict[str, list] = {}
    for r in rows:
        tags = [t for t, flag in (("vegetariano", r["vegetarian"]), ("vegano", r["vegan"]),
                                  ("senza glutine", r["gluten_free"])) if flag]
        menu.setdefault(r["category"], []).append({
            "piatto": r["name"], "descrizione": r["description"], "prezzo_euro": r["price"],
            "allergeni": r["allergens"] or "nessuno", "caratteristiche": tags,
        })
    if diet and not menu:
        return {"nota": f"Nessun piatto {diet} in questa categoria."}
    return menu


def get_info(conn) -> dict:
    info = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM restaurant_info")}
    if "orari" in info:
        info["orari"] = json.loads(info["orari"])
    return info
