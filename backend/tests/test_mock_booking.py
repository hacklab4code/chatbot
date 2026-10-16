"""Test del flusso conversazionale di prenotazione con richiesta del numero di telefono."""
from datetime import date, timedelta
import pytest

from app import config, db
from app.agent import Agent
from app.llm import OllamaClient


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "mock_agent.db")
    c = db.connect()
    db.init_db(c)
    c.close()


def test_full_booking_flow_asks_phone_number():
    # Usa il client Ollama in modalità mock
    client = OllamaClient(model="mock")
    agent = Agent(client)
    sid = "test-phone-session-1"

    # Passo 1: l'utente vuole prenotare -> chiede le persone
    r1 = agent.handle(sid, "Vorrei prenotare un tavolo")
    assert "quante persone" in r1["reply"].lower()

    # Passo 2: 2 persone -> chiede il giorno
    r2 = agent.handle(sid, "Siamo in 2")
    assert "quale giorno" in r2["reply"].lower()

    # Troviamo una data valida non lunedì (ad es. domani o dopodomani)
    target = date.today() + timedelta(days=1)
    if target.weekday() == 0:  # lunedì chiuso
        target += timedelta(days=1)
    target_str = target.strftime("%d/%m/%Y")

    # Passo 3: giorno indicato -> chiede l'orario
    r3 = agent.handle(sid, f"Per il {target_str}")
    assert "che ora" in r3["reply"].lower()

    # Passo 4: orario indicato -> verifica disponibilità e chiede il nome
    r4 = agent.handle(sid, "Alle 20:30")
    assert "nome" in r4["reply"].lower()
    assert any(a["tool"] == "check_availability" for a in r4["actions"])

    # Passo 5: nome indicato -> DEVE chiedere anche il numero di telefono!
    r5 = agent.handle(sid, "Mario Rossi")
    assert ("telefono" in r5["reply"].lower() or "recapito" in r5["reply"].lower())
    # Non deve aver ancora creato la prenotazione senza telefono
    assert not any(a["tool"] == "create_reservation" for a in r5["actions"])

    # Passo 6: numero di telefono indicato -> crea la prenotazione e conferma con codice e telefono
    r6 = agent.handle(sid, "333 1234567")
    assert any(a["tool"] == "create_reservation" for a in r6["actions"])
    create_act = next(a for a in r6["actions"] if a["tool"] == "create_reservation")
    assert create_act["arguments"]["customer_name"] == "Mario Rossi"
    assert create_act["arguments"]["contact"] == "333 1234567"
    assert "confermata con successo" in r6["reply"].lower()
    assert "333 1234567" in r6["reply"] or "Telefono" in r6["reply"]


def test_booking_with_privacy_pseudonymized_tokens():
    client = OllamaClient(model="mock")
    agent = Agent(client)
    sid = "test-phone-session-privacy"

    target = date.today() + timedelta(days=2)
    if target.weekday() == 0:
        target += timedelta(days=1)
    target_str = target.strftime("%d/%m/%Y")

    agent.handle(sid, "Vorrei prenotare un tavolo")
    agent.handle(sid, "4 persone")
    agent.handle(sid, f"per il giorno {target_str}")
    r4 = agent.handle(sid, "alle 20:00")
    assert "nome" in r4["reply"].lower()

    # Fornisce il token privacy del nome [NOME_5993E2]
    r5 = agent.handle(sid, "Il nome è [NOME_5993E2]")
    assert ("telefono" in r5["reply"].lower() or "recapito" in r5["reply"].lower())

    # Fornisce il token privacy del telefono [TEL_DA308D]
    r6 = agent.handle(sid, "il mio recapito è [TEL_DA308D]")
    assert any(a["tool"] == "create_reservation" for a in r6["actions"])
    create_act = next(a for a in r6["actions"] if a["tool"] == "create_reservation")
    assert create_act["arguments"]["customer_name"] == "[NOME_5993E2]"
    assert create_act["arguments"]["contact"] == "[TEL_DA308D]"
    assert "[TEL_DA308D]" in r6["reply"]


def test_booking_recognizes_date_first_named_month():
    client = OllamaClient(model="mock")
    agent = Agent(client)
    sid = "test-session-29-ottobre"

    # L'utente scrive PRENOTARE PER 29 OTTOBRE
    r1 = agent.handle(sid, "PRENOTARE PER 29 OTTOBRE")
    # NON deve confondere 29 con 29 persone dicendo "massimo di 10 persone"
    assert "massimo di" not in r1["reply"]
    assert "10 persone" not in r1["reply"]
    # Deve aver compreso la data e chiedere per quante persone
    assert "quante persone" in r1["reply"].lower()
    assert "29/10" in r1["reply"]

    # Risponde con il numero di persone
    r2 = agent.handle(sid, "2")
    # Avendo ora sia persone che data, deve chiedere l'orario
    assert "che ora" in r2["reply"].lower()


def test_booking_recognizes_date_day_number_only():
    client = OllamaClient(model="mock")
    agent = Agent(client)
    sid = "test-session-per-29"

    # L'utente scrive VOLGIO PRENOTARE PER 29
    r1 = agent.handle(sid, "VOLGIO PRENOTARE PER 29")
    # NON deve confondere 29 con 29 persone
    assert "massimo di" not in r1["reply"]
    assert "10 persone" not in r1["reply"]
    assert "quante persone" in r1["reply"].lower()
    assert "29/" in r1["reply"]

    # Risponde con 4 persone
    r2 = agent.handle(sid, "Siamo in 4")
    assert "che ora" in r2["reply"].lower()


def test_booking_large_party_explicit_persone_triggers_limit():
    client = OllamaClient(model="mock")
    agent = Agent(client)
    sid = "test-session-large-party"

    # Se l'utente specifica ESPLICITAMENTE persone oltre 10
    r1 = agent.handle(sid, "Vorrei prenotare per 29 persone")
    assert "massimo di" in r1["reply"]
    assert "10 persone" in r1["reply"]
    assert "+39 02 1234 5678" in r1["reply"]


def test_booking_with_both_party_and_date_in_first_message():
    client = OllamaClient(model="mock")
    agent = Agent(client)
    sid = "test-session-party-and-date"

    # Fornisce subito persone e data
    r1 = agent.handle(sid, "Vorrei un tavolo per 4 persone per il 29")
    assert "massimo di" not in r1["reply"]
    # Entrambi noti -> chiede subito l'orario
    assert "che ora" in r1["reply"].lower()
    assert "4 persone" in r1["reply"]
    assert "29/" in r1["reply"]


def test_booking_update_party_size_with_siamo_5():
    client = OllamaClient(model="mock")
    agent = Agent(client)
    sid = "test-session-party-update"

    agent.handle(sid, "PRENOTARE PER 29 OTTOBRE")
    r2 = agent.handle(sid, "4")
    assert "4 persone" in r2["reply"]

    # L'utente corregge con 'SO SIAMO 5'
    r3 = agent.handle(sid, "SO SIAMO 5")
    assert "5 persone" in r3["reply"]
    assert "4 persone" not in r3["reply"]
    assert "29/10" in r3["reply"]


def test_booking_does_not_treat_greeting_ciao_as_name():
    client = OllamaClient(model="mock")
    agent = Agent(client)
    sid = "test-session-ciao-not-name"

    # L'utente dice CIAO all'inizio
    r1 = agent.handle(sid, "CIAO")
    assert "benvenuto" in r1["reply"].lower() or "aiutarla" in r1["reply"].lower()

    # Poi prenota per domani
    r2 = agent.handle(sid, "PRENOTAIZNE PER DOMANI")
    assert "quante persone" in r2["reply"].lower()

    # 5 persone
    r3 = agent.handle(sid, "5")
    assert "che ora" in r3["reply"].lower()

    # Ore 12
    r4 = agent.handle(sid, "12")
    # Il bot DEVE chiedere il nome e NON deve dire 'a nome CIAO'
    assert "nome ciao" not in r4["reply"].lower()
    assert "a nome **ciao**" not in r4["reply"].lower()
    assert "nome" in r4["reply"].lower()
    assert ("quale nome" in r4["reply"].lower() or "intestarla" in r4["reply"].lower())

    # L'utente fornisce il suo vero nome
    r5 = agent.handle(sid, "Marco Rossi")
    assert "marco rossi" in r5["reply"].lower()
    assert "telefono" in r5["reply"].lower() or "recapito" in r5["reply"].lower()

    # L'utente fornisce il telefono
    r6 = agent.handle(sid, "32452345243")
    assert "confermata con successo" in r6["reply"].lower()
    assert "Marco Rossi" in r6["reply"]
    assert "CIAO" not in r6["reply"]


def test_agent_safeguard_blocks_tool_call_without_user_date():
    """Se l'LLM tentasse di invocare create_reservation o check_availability
    inventando una data mai menzionata dall'utente, il guard di Agent.handle deve bloccarla."""
    class HallucinatingDateLLM:
        def __init__(self):
            self.called = False

        def chat(self, messages, tools=None):
            last_msg = messages[-1]
            if last_msg.get("role") == "tool" and "ERRORE TASSATIVO" in last_msg.get("content", ""):
                return {
                    "role": "assistant",
                    "content": "Per quale giorno desidera prenotare il tavolo?",
                }
            if not self.called:
                self.called = True
                return {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{
                        "function": {
                            "name": "create_reservation",
                            "arguments": {
                                "date": "2026-10-16",
                                "time": "21:45",
                                "party_size": 6,
                                "customer_name": "Matteo",
                                "contact": "3331234567"
                            }
                        }
                    }]
                }
            return {"role": "assistant", "content": "Risposta completata"}

    agent = Agent(HallucinatingDateLLM())
    sid = "test-no-date-block"

    # L'utente ha indicato solo orario, persone e nome, MA MAI la data
    res = agent.handle(sid, "Sono Matteo, vorrei per le 22 per 6 persone tel 3331234567")

    # La chiamata create_reservation deve essere stata bloccata dal guard
    assert any(a["tool"] == "create_reservation" and a["ok"] is False for a in res["actions"])
    assert "Per quale giorno desidera prenotare" in res["reply"]

    # Verifichiamo che nessuna prenotazione sia stata creata nel DB
    c = db.connect()
    rows = c.execute("SELECT * FROM reservations").fetchall()
    c.close()
    assert len(rows) == 0




