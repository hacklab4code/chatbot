# Sistema AI per la prenotazione di un tavolo: Ristorante Zio Pierino PSG

> ⚡ **Avvio Rapido Demo**: `./0_AVVIA_DEMO_LOCALE.sh` (oppure doppio clic su `0_AVVIA_DEMO_LOCALE.command`)  
> 🧹 **Reset Database Prenotazioni**: `./0_RESET_PRENOTAZIONI_DEMO.sh`  
> 🎙️ **Avvio Voicebot**: `./avvia_voice.sh`

Progetto di gruppo (Traccia 3). Si compone di tre componenti indipendenti che comunicano **solo tramite la rete**.

| cartella | componente | descrizione |
|---|---|---|
| [`backend/`](backend/README.md) | **BE** | Python + FastAPI + LLM locale (Ollama) + SQLite |
| [`chat/`](chat/README.md) | **CHAT** | Chatbot Web e da terminale con pseudonimizzazione GDPR |
| [`voice/`](voice/README.md) | **VOICE** | Voicebot con STT (Whisper) e TTS locali |

```
 Macchina B (CHAT)                     Macchina A (BE)                    Macchina C (VOICE)
┌───────────────────────┐            ┌──────────────────────────┐        ┌───────────────────────────┐
│ browser / terminale   │            │ FastAPI  :8000           │        │ microfono → Whisper (STT) │
│ pseudonimizzazione    │──HTTP LAN─►│ agente LLM ◄─► Ollama    │◄─HTTP──│ pseudonimizzazione        │
│ vault locale dei dati │  X-API-Key │ strumenti ◄─► SQLite     │  LAN   │ voce di sistema (TTS)     │
└───────────────────────┘            └──────────────────────────┘        └───────────────────────────┘
```

## Come la soluzione rispetta i vincoli
| vincolo | soluzione |
|---|---|
| 1. Tre macchine diverse | Tre progetti separati, ognuno con il proprio ambiente, i propri requisiti e la propria configurazione `.env`. CHAT e VOICE trovano il BE tramite `BE_URL`. |
| 2. Comunicazione via rete | HTTP/JSON sulla LAN (contratto in [docs/API.md](docs/API.md)), protetto da una API key condivisa. |
| 3. Pre-processing dei dati personali | CHAT e VOICE sostituiscono nomi, telefoni, email, CF, IBAN e carte con segnaposto HMAC (`[NOME_3FA9C1]`) **prima** dell'invio. La tabella di corrispondenza resta solo sul client. Il BE fa un secondo controllo e oscura qualunque dato arrivato in chiaro. |
| 4. Modelli in locale | LLM su Ollama (`qwen3-coder:30b`), STT con faster-whisper, TTS con le voci di sistema. Nessun servizio cloud. |
| 5. Due stakeholder | [Presentazione tecnica](docs/presentazione_tecnica.md) e [presentazione per il ristoratore](docs/presentazione_ristoratore.md). |
| 6. Tre progetti | Le cartelle sono autonome: ognuna può diventare un repository separato. |

## Casi d'uso coperti
1. Prenotazione di un tavolo, con verifica della disponibilità e proposta di orari alternativi
2. Modifica di una prenotazione: data, ora, persone o note (identificata dal codice di 6 cifre)
3. Cancellazione di una prenotazione
4. Consultazione del menu, con filtri vegetariano, vegano e senza glutine e indicazione degli allergeni
5. Informazioni su indirizzo, come arrivare, contatti, orari, accessibilità, animali e pagamenti

## Avvio in rete (tre macchine)
1. **Macchina A (BE):** installare Ollama e il modello, poi impostare `backend/.env` con `BE_API_KEY`. Avviare con `python -m app.main` e aprire la porta 8000 nel firewall.
2. **Macchina B (CHAT):** in `chat/.env` impostare `BE_URL=http://<IP-A>:8000` e la stessa `BE_API_KEY`. Avviare con `python -m chat_app.server` e aprire `http://localhost:8001`.
3. **Macchina C (VOICE):** in `voice/.env` impostare `BE_URL=http://<IP-A>:8000` e la stessa `BE_API_KEY`. Avviare con `python -m voice_bot.main`.

Le istruzioni dettagliate sono nei README dei singoli progetti.

## Demo su un solo PC
Per avviare backend e chatbot insieme su una sola macchina:
```bash
./0_AVVIA_DEMO_LOCALE.sh
```
Oppure su macOS fare doppio clic su `0_AVVIA_DEMO_LOCALE.command`.
Per avviare anche il voicebot vocale:
```bash
./avvia_voice.sh
```

## Test
| progetto | test | cosa verificano |
|---|---|---|
| backend | 27 | regole di prenotazione, sovrapposizioni, modifica e cancellazione, filtri del menu, API key, oscuramento, ciclo agente con LLM finto, recupero delle tool call scritte come testo |
| chat | 23 | riconoscimento dei dati personali, assenza di falsi positivi su date, orari e codici, round-trip di pseudonimizzazione e re-identificazione |
| voice | 32 | gli stessi test di privacy, più normalizzazione del parlato, testo per la sintesi vocale e pipeline completa senza dati personali verso il BE |

Sono stati verificati anche end-to-end con il modello reale: prenotazione, modifica, cancellazione, menu, informazioni, giorno di chiusura e richieste fuori tema, sia via chat (browser) sia via voce (file audio trascritti da Whisper).
