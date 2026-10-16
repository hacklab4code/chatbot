"""Accesso al database SQLite: schema, dati iniziali e connessioni."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS restaurant_tables (
    id      INTEGER PRIMARY KEY,
    name    TEXT NOT NULL UNIQUE,
    seats   INTEGER NOT NULL CHECK (seats > 0),
    area    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reservations (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    code             TEXT NOT NULL UNIQUE,
    date             TEXT NOT NULL,          -- YYYY-MM-DD
    time             TEXT NOT NULL,          -- HH:MM
    party_size       INTEGER NOT NULL CHECK (party_size > 0),
    table_id         INTEGER NOT NULL REFERENCES restaurant_tables(id),
    customer_alias   TEXT,                   -- solo pseudonimo, mai dati personali in chiaro
    contact_alias    TEXT,                   -- solo pseudonimo, mai dati personali in chiaro
    notes            TEXT,
    channel          TEXT,                   -- chat / voice / api
    status           TEXT NOT NULL DEFAULT 'confermata',
    created_at       TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at       TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_res_date ON reservations(date, status);

CREATE TABLE IF NOT EXISTS menu_items (
    id          INTEGER PRIMARY KEY,
    category    TEXT NOT NULL,
    name        TEXT NOT NULL,
    description TEXT NOT NULL,
    price       REAL NOT NULL,
    allergens   TEXT NOT NULL DEFAULT '',
    vegetarian  INTEGER NOT NULL DEFAULT 0,
    vegan       INTEGER NOT NULL DEFAULT 0,
    gluten_free INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS restaurant_info (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

TABLES = [
    ("T1", 2, "sala interna"), ("T2", 2, "sala interna"), ("T3", 2, "dehors"), ("T4", 2, "dehors"),
    ("T5", 4, "sala interna"), ("T6", 4, "sala interna"), ("T7", 4, "sala interna"),
    ("T8", 4, "dehors"), ("T9", 4, "dehors"),
    ("T10", 6, "sala interna"), ("T11", 6, "dehors"),
    ("T12", 8, "saletta privata"), ("T13", 10, "saletta privata"),
]

# (categoria, nome, descrizione, prezzo, allergeni, vegetariano, vegano, senza glutine)
MENU = [
    ("Antipasti", "Tagliere Zio Pierino PSG", "Selezione di salumi e formaggi marchigiani con giardiniera artigianale", 16.0, "latte", 0, 0, 1),
    ("Antipasti", "Burrata e pomodorini", "Burrata pugliese, pomodorini confit e basilico", 12.0, "latte", 1, 0, 1),
    ("Antipasti", "Vitello tonnato", "Girello di vitello, salsa tonnata e capperi", 14.0, "uova, pesce", 0, 0, 1),
    ("Antipasti", "Hummus di ceci", "Hummus di ceci, verdure croccanti e pane carasau", 10.0, "sesamo, glutine", 1, 1, 0),
    ("Primi", "Risotto alla milanese", "Carnaroli, zafferano e midollo", 15.0, "latte", 0, 0, 1),
    ("Primi", "Tagliatelle al ragù", "Pasta fresca all'uovo con ragù di manzo cotto 6 ore", 14.0, "glutine, uova, sedano", 0, 0, 0),
    ("Primi", "Spaghetti alle vongole", "Spaghetti di Gragnano, vongole veraci e prezzemolo", 17.0, "glutine, molluschi", 0, 0, 0),
    ("Primi", "Gnocchi al pomodoro", "Gnocchi di patate, pomodoro San Marzano e basilico", 12.0, "glutine", 1, 1, 0),
    ("Secondi", "Cotoletta alla milanese", "Costoletta di vitello con osso, patate al forno", 26.0, "glutine, uova, latte", 0, 0, 0),
    ("Secondi", "Filetto di branzino", "Branzino al forno con verdure di stagione", 22.0, "pesce", 0, 0, 1),
    ("Secondi", "Tagliata di manzo", "Tagliata con rucola e scaglie di grana", 24.0, "latte", 0, 0, 1),
    ("Secondi", "Parmigiana di melanzane", "Melanzane, pomodoro, mozzarella e parmigiano", 14.0, "latte", 1, 0, 1),
    ("Dolci", "Tiramisù della casa", "Savoiardi, mascarpone e caffè", 7.0, "glutine, uova, latte", 1, 0, 0),
    ("Dolci", "Panna cotta ai frutti di bosco", "Panna cotta con coulis di frutti di bosco", 6.0, "latte", 1, 0, 1),
    ("Dolci", "Sorbetto al limone", "Sorbetto artigianale al limone", 5.0, "", 1, 1, 1),
    ("Bevande", "Acqua minerale 75cl", "Naturale o frizzante", 3.0, "", 1, 1, 1),
    ("Bevande", "Vino della casa (calice)", "Rosso o bianco", 6.0, "solfiti", 1, 1, 1),
    ("Bevande", "Caffè espresso", "", 2.0, "", 1, 1, 1),
]

INFO = {
    "nome": "Ristorante Zio Pierino PSG",
    "indirizzo": "Lungomare Antonio Gramsci 42, 63822 Porto San Giorgio (FM)",
    "come_arrivare": "Sul suggestivo Lungomare di Porto San Giorgio (PSG), a 5 minuti a piedi dalla stazione FS Porto San Giorgio-Fermo e dal Porto Peschereccio; comodo parcheggio sul lungomare.",
    "telefono": "+39 0734 678910",
    "email": "info@ziopierinopsg.it",
    "sito_web": "www.ziopierinopsg.it",
    "orari": json.dumps({
        "lunedi": "chiuso",
        "martedi-domenica pranzo": "12:00-15:00 (ultima prenotazione 14:00)",
        "martedi-domenica cena": "19:00-23:30 (ultima prenotazione 22:00)",
    }, ensure_ascii=False),
    "accessibilita": "Locale accessibile in sedia a rotelle, vista mare, bagno attrezzato.",
    "animali": "Animali di piccola taglia ammessi nel dehors vista mare.",
    "pagamenti": "Contanti, carte di credito e debito, bancomat, Apple Pay e Google Pay.",
    "allergie": "Su richiesta prepariamo piatti senza glutine; segnalare allergie al momento della prenotazione.",
    "gruppi": "Per gruppi oltre 10 persone o eventi privati contattare il ristorante per telefono.",
    "numero_tavoli": "13",
    "capienza_massima_coperti": "58",
    "max_persone_online": "10",
}

# Orari prenotabili: (inizio, ultima prenotazione)
SERVICES = {"pranzo": ("12:00", "14:00"), "cena": ("19:00", "22:00")}
CLOSED_WEEKDAYS = {0}  # 0 = lunedì


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = Path(db_path or config.DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    # isolation_level=None: niente transazioni implicite, le gestiamo con transaction()
    conn = sqlite3.connect(path, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection):
    """Transazione esplicita: BEGIN IMMEDIATE evita doppie prenotazioni concorrenti."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def init_db(conn: sqlite3.Connection) -> None:
    """Crea lo schema e inserisce i dati iniziali se il DB è vuoto."""
    conn.executescript(SCHEMA)
    if conn.execute("SELECT COUNT(*) FROM restaurant_tables").fetchone()[0] == 0:
        conn.executemany("INSERT INTO restaurant_tables(name, seats, area) VALUES (?, ?, ?)", TABLES)
    if conn.execute("SELECT COUNT(*) FROM menu_items").fetchone()[0] == 0:
        conn.executemany(
            "INSERT INTO menu_items(category, name, description, price, allergens, vegetarian, vegan, gluten_free)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            MENU,
        )
    if conn.execute("SELECT COUNT(*) FROM restaurant_info").fetchone()[0] == 0:
        conn.executemany("INSERT INTO restaurant_info(key, value) VALUES (?, ?)", INFO.items())
    conn.commit()
