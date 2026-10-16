# CHAT: chat-bot di prenotazione (Membro 2)

Il chat-bot ha un'interfaccia web servita da un piccolo server Python. Il server **pseudonimizza i dati personali** prima di inoltrare il messaggio al BE tramite la rete, e rimette i dati reali nella risposta prima di mostrarla all'utente.

```
browser ──► server CHAT (questa macchina) ──[testo pseudonimizzato]──► BE (LAN)
            │ privacy.py: "Mario Rossi" → [NOME_3FA9C1]
            └ vault locale data/vault.json (non lascia mai la macchina)
```

## Struttura
| file | ruolo |
|---|---|
| `chat_app/server.py` | server web (FastAPI): pagina della chat + `/api/message` |
| `chat_app/static/index.html` | interfaccia della chat (responsive, tema chiaro e scuro) |
| `chat_app/cli.py` | versione da terminale |
| `chat_app/privacy.py` | riconoscimento dei dati personali e pseudonimizzazione HMAC con vault locale |
| `chat_app/be_client.py` | client HTTP verso il BE |

## Installazione e avvio
```bash
python -m venv .venv
```
```bash
.venv\Scripts\python -m pip install -r requirements-dev.txt
```
Copiare `.env.example` in `.env`, poi impostare `BE_URL` (l'IP del BE nella LAN) e `BE_API_KEY`.
```bash
.venv\Scripts\python -m chat_app.server
```
Poi aprire `http://localhost:8001`, oppure `http://<ip-macchina-chat>:8001` da un altro dispositivo.

Versione da terminale:
```bash
.venv\Scripts\python -m chat_app.cli
```

## Privacy
Questi dati vengono riconosciuti e sostituiti: nomi (dopo frasi come "mi chiamo", "a nome di", "sono…", oppure nomi propri comuni), telefoni, email, codici fiscali, IBAN e carte (validate con l'algoritmo di Luhn). Date, orari, numero di persone e codici di prenotazione restano invece in chiaro, perché servono al BE.

Il segnaposto è un HMAC-SHA256 calcolato con una chiave segreta locale (`data/secret.key`), quindi il BE non può risalire al dato. Lo stesso dato produce sempre lo stesso segnaposto: il ristorante vede quindi un cliente ricorrente come la stessa persona, senza conoscerne l'identità.

L'interfaccia mostra (disattivabile) il testo che è stato effettivamente inviato al server.

## Test
```bash
.venv\Scripts\python -m pytest -q
```
