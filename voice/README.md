# VOICE: voice-bot di prenotazione (Membro 3)

Il voice-bot permette di prenotare parlando. Riconoscimento e sintesi vocale girano **in locale** su questa macchina, mentre il BE viene raggiunto tramite la LAN.

```
microfono ─► VAD ─► STT faster-whisper ─► normalizzazione parlato ─► pseudonimizzazione
                                                                            │ (rete)
altoparlanti ◄─ TTS (voci di sistema) ◄─ adattamento per la voce ◄─ re-identificazione ◄─ BE
```

## Struttura
| file | ruolo |
|---|---|
| `voice_bot/main.py` | ciclo di conversazione e modalità di avvio |
| `voice_bot/audio.py` | acquisizione dal microfono con rilevamento automatico di inizio e fine frase |
| `voice_bot/stt.py` | speech-to-text locale (faster-whisper) e lettura dei WAV |
| `voice_bot/tts.py` | text-to-speech locale (pyttsx3: SAPI su Windows, eSpeak su Linux) |
| `voice_bot/spoken.py` | adattamenti tra parlato e testo: "chiocciola" → @, cifre dette a parole, orari, prezzi e codici pronunciabili |
| `voice_bot/privacy.py` | pseudonimizzazione (stesso modulo del chat-bot) |
| `voice_bot/be_client.py` | client HTTP verso il BE |

## Installazione
```bash
python -m venv .venv
```
```bash
.venv\Scripts\python -m pip install -r requirements-dev.txt
```
Copiare `.env.example` in `.env`, poi impostare `BE_URL` e `BE_API_KEY`.

Al primo avvio il modello Whisper (`small`, circa 480 MB) viene scaricato in `models/`. Dopo, tutto funziona offline.

Su Windows serve una voce italiana installata (di solito "Microsoft Elsa"). Se manca, si aggiunge da Impostazioni → Ora e lingua → Voce.

## Avvio
```bash
.venv\Scripts\python -m voice_bot.main
```
| opzione | effetto |
|---|---|
| `--text` | si scrive invece di parlare, ma le risposte vengono comunque lette ad alta voce |
| `--no-tts` | le risposte vengono solo stampate |
| `--wav a.wav b.wav` | elabora file audio registrati, utile per demo ripetibili |
| `--quiet` | non mostra il testo inviato al server |

Per chiudere basta dire "arrivederci", oppure premere Ctrl+C.

Il modello Whisper usa la GPU se CUDA è disponibile, altrimenti passa automaticamente alla CPU. Per frasi brevi la CPU va bene. Per maggiore precisione si può usare `WHISPER_MODEL=medium`.

## Test
```bash
.venv\Scripts\python -m pytest -q
```
