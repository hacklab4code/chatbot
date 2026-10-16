# BE: backend di prenotazione (Membro 1)

Questo backend in Python (FastAPI) contiene l'**LLM locale** (tramite Ollama) e il **database SQLite**. CHAT e VOICE lo usano tramite la rete. Il contratto è descritto in [../docs/API.md](../docs/API.md).

## Struttura
| file | ruolo |
|---|---|
| `app/main.py` | API HTTP, API key, controllo privacy in ingresso |
| `app/agent.py` | prompt di sistema, memoria delle sessioni, ciclo LLM ↔ strumenti |
| `app/tools.py` | strumenti (function calling) messi a disposizione dell'LLM |
| `app/services.py` | regole di business deterministiche: validazioni, disponibilità, CRUD delle prenotazioni |
| `app/db.py` | schema SQLite e dati iniziali (tavoli, menu, informazioni) |
| `app/llm.py` | client HTTP per Ollama e normalizzazione delle risposte del modello |
| `app/privacy_guard.py` | oscuramento di sicurezza dei dati personali eventualmente arrivati in chiaro |

## Installazione
1. Installare [Ollama](https://ollama.com) e scaricare un modello con supporto ai tool:
   ```bash
   ollama pull qwen3-coder:30b
   ```
   Su macchine con meno memoria si può usare `qwen2.5:7b` impostando `LLM_MODEL=qwen2.5:7b`. Se il modello configurato non c'è, il BE usa il primo modello disponibile e lo segnala nel log.
2. Creare l'ambiente Python (versione 3.11 o successiva):
   ```bash
   python -m venv .venv
   ```
   ```bash
   .venv\Scripts\python -m pip install -r requirements-dev.txt
   ```
3. Copiare `.env.example` in `.env` e impostare una `BE_API_KEY`, che va condivisa con CHAT e VOICE.

## Avvio
```bash
.venv\Scripts\python -m app.main
```
Al primo avvio il database `data/ristorante.db` viene creato con i dati iniziali. Su Windows bisogna consentire la porta 8000 nel firewall, così CHAT e VOICE possono raggiungerla dalla LAN.

## Test
```bash
.venv\Scripts\python -m pytest -q
```
I test non richiedono l'LLM: usano un modello finto e un database temporaneo.

## Regole di prenotazione
- Il ristorante è chiuso il lunedì. Si prenota a pranzo dalle 12:00 alle 14:00 e a cena dalle 19:00 alle 22:00.
- Si accettano da 1 a 10 persone e si può prenotare fino a 60 giorni in anticipo. Non si prenota nel passato.
- Ogni prenotazione occupa il tavolo per 2 ore. Viene assegnato il tavolo libero più piccolo che basta, con al massimo 4 posti vuoti.
- Il codice di prenotazione è di 6 cifre, quindi facile da dettare al telefono.
- Le scritture usano `BEGIN IMMEDIATE`: due richieste contemporanee non possono prenotare lo stesso tavolo.
