#!/usr/bin/env python3
"""Pulisce le prenotazioni di test dal database mantenendo intatti tavoli e menu.
Utile da lanciare prima di una presentazione o demo dal vivo.
"""
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "backend" / "data" / "ristorante.db"
VAULT_CHAT = ROOT / "chat" / "data" / "vault.json"
VAULT_PC2 = ROOT / "pacchetti_tre_pc" / "PC2_CHAT" / "data" / "vault.json"

def reset():
    if DB_PATH.exists():
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("DELETE FROM reservations;")
        conn.commit()
        conn.close()
        print("✅ Tabella prenotazioni (reservations) svuotata con successo!")
    else:
        print("⚠️ Database ristorante.db non trovato.")

    # Svuota i vault locali
    for v in [VAULT_CHAT, VAULT_PC2]:
        if v.parent.exists():
            v.write_text("{}", encoding="utf-8")
            print(f"✅ Vault pulito in {v.relative_to(ROOT)}")

    print("\n🎉 Sistema pulito e pronto per una nuova dimostrazione da zero!")

if __name__ == "__main__":
    reset()
