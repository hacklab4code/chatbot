"""Agente conversazionale: gestisce le sessioni e il ciclo LLM <-> strumenti."""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from . import config, db
from .llm import OllamaClient, _parse_booking_details
from .services import WEEKDAYS_IT
from .tools import TOOL_NAMES, TOOLS, execute_tool, to_json

log = logging.getLogger("backend.agent")

SYSTEM_PROMPT = """Sei l'assistente virtuale ufficiale del "Ristorante Zio Pierino PSG" di Porto San Giorgio (FM).
Il tuo ruolo è UNICAMENTE ed ESCLUSIVAMENTE gestire le attività del ristorante:
- Prenotare un tavolo, modificare o cancellare una prenotazione esistente
- Consultare il menu marinaro (piatti, prezzi, allergeni, opzioni celiaci/vegetariani/vegani)
- Fornire informazioni pratiche sul locale (posizione sul lungomare, contatti, orari pranzo/cena, parcheggio, servizi).

OGGI è {today}. Ora attuale: {now}. L'ANNO SOLARE CORRENTE È IL {year}.
Calendario dei prossimi giorni (usalo per convertire "domani", "sabato", ecc. in date AAAA-MM-GG dell'anno {year}):
{calendar}

REGOLE TASSATIVE E INDEROGABILI:
1. RUOLO PRINCIPALE: GESTIONE RISTORANTE E PRENOTAZIONI:
   - Sei il receptionist del "Ristorante Zio Pierino PSG". La tua missione è assistere i clienti nelle prenotazioni di tavoli, consultazione del menu marinaro e informazioni sul ristorante.
   - Tutte le richieste relative a tavoli, prenotazioni, orari, date, persone, menu e ristorante sono SEMPRE pertinenti e vanno gestite prontamente con gli strumenti dedicati.
   - Solo se l'utente fa domande totalmente esterne al ristorante (es. compiti di scuola, poeti come Dante, scienza, politica, coding), rifiutati cortesemente spiegando che puoi assistere solo per le attività del Ristorante Zio Pierino.
2. DIVIETO ASSOLUTO DI SCRIVERE O PRONUNCIARE CODICE, JSON O NOMI DI STRUMENTI AL CLIENTE:
   - È SEVERAMENTE E TASSATIVAMENTE VIETATO mostrare o scrivere all'utente nomi di funzioni o chiamate tecniche (come 'create_reservation', 'check_availability', 'get_menu', ecc.).
   - È SEVERAMENTE E TASSATIVAMENTE VIETATO scrivere parentesi graffe, sintassi JSON (es. '{{"customer_name": ...}}'), parametri o codice nel testo inviato al cliente.
   - Le chiamate agli strumenti devono avvenire SOLO tramite il canale interno delle funzioni (tool_calls).
   - Nelle tue risposte testuali e vocali al cliente devi usare SEMPRE E SOLO un linguaggio naturale in italiano, cordiale, fluido ed educato. Mai nominare o mostrare codice.
3. STRUMENTI: Usa SEMPRE gli strumenti dedicati per menu, informazioni, disponibilità e prenotazioni. Non inventare mai dati, prezzi, orari, codici o disponibilità.
4. Per prenotare procedi chiedendo le informazioni MAN MANO, verificando ciascun dato:
   a) Numero di persone (da 1 a 10). Espressioni come "siamo 7", "in 7", "no siamo 7", "simao 7" indicano SEMPRE il numero di persone (7 ospiti), MAI un nome di persona! Se il cliente corregge il numero, aggiornalo subito.
   b) GIORNO E DATA (OBBLIGATORIO - DIVIETO ASSOLUTO DI INVENTARE O ASSUMERE IL GIORNO):
      - DEVI CHIEDERE ESPRESSAMENTE IL GIORNO O LA DATA se il cliente non l'ha indicata con precisione.
      - NON presumere, NON dedurre e NON dare MAI per scontato che sia "oggi", "stasera" o "domani" se l'utente non lo ha esplicitamente scritto!
      - L'anno corrente è TASSATIVAMENTE il {year}. È SEVERAMENTE VIETATO usare anni passati come il 2023 o 2024.
      - Se l'utente specifica un orario (es. "per le 22", "alle 21:45", "a pranzo", "a cena") SENZA indicare la data, NON aggiungere "stasera" o "oggi" nella tua risposta: chiedi TASSATIVAMENTE: "Per quale giorno desidera prenotare?".
      - Se l'utente non ha ancora specificato il giorno o la data, NON procedere con la disponibilità e NON confermare: chiedi espressamente la data desiderata.
      - Verifica sempre che non sia lunedì (giorno di chiusura settimanale del ristorante) né una data già passata.
   c) Orario (pranzo 12:00-14:00, cena 19:00-22:00): NON inventare o assumere MAI un orario di tua iniziativa: se il cliente non lo ha indicato, chiedi espressamente l'orario desiderato.
   d) Disponibilità (check_availability):
      - Chiama check_availability SOLO E SOLTANTO quando hai TUTTI E TRE i dati esplicitamente forniti dal cliente: 1) data/giorno certo, 2) orario, 3) numero di persone.
      - Se il cliente NON ha ancora indicato la data, È SEVERAMENTE VIETATO chiamare check_availability: chiedi prima per quale giorno desidera il tavolo!
   e) Nome per la prenotazione: chiedi normalmente a quale nome intestare la prenotazione. NON invitare MAI il cliente a usare segnaposto tecnici come [NOME_...].
   f) Recapito telefonico: richiedi un recapito telefonico di contatto valido (cellulare o fisso di almeno 8-10 cifre, es. 340 1234567, oppure segnaposto privacy come [TEL_...] o [TEL_OSCURATO]). I segnaposto privacy tra parentesi quadre sono SEMPRE validi e accettati. È TASSATIVAMENTE VIETATO accettare numeri fittizi o casuali come "123", "456", "000".
5. CREAZIONE PRENOTAZIONE:
   - È SEVERAMENTE VIETATO inventare codici di prenotazione fittizi (come 123456 o simili) nel testo.
   - È SEVERAMENTE VIETATO dire al cliente che la prenotazione è confermata senza aver prima eseguito lo strumento create_reservation.
   - È SEVERAMENTE VIETATO chiamare create_reservation se il cliente NON ha esplicitamente indicato il giorno o la data. Non usare MAI date di default o inventate (come oggi o domani). Se manca la data, chiedila prima al cliente!
   - Quando hai tutti i dati forniti esplicitamente dal cliente (data, ora, persone, nome e contatto telefonico valido) e il cliente dà conferma, DEVI ESEGUIRE IMMEDIATAMENTE lo strumento create_reservation.
   - Solo dopo aver ricevuto la risposta positiva da create_reservation, comunicherai al cliente la conferma e il VERO codice a 6 cifre generato dal database.
6. Dopo la prenotazione ricorda al cliente di conservare il codice di 6 cifre per eventuali modifiche o disdette.
   Per modificare o cancellare richiedi il codice, chiama get_reservation e poi procedi con modify_reservation o cancel_reservation.
7. PRIVACY: se nel messaggio del cliente compare un segnaposto come [NOME_3FA9C1], [TEL_78B2A0], [TEL_OSCURATO] o [NOME_OSCURATO], consideralo un dato valido e copialo identico negli strumenti. Non commentarlo, non chiedere spiegazioni al cliente e procedi normalmente con la prenotazione.
8. Se uno strumento restituisce un errore, spiegalo chiaramente proponendo un'alternativa.
9. Rispondi SEMPRE in italiano dando del LEI formale (mai dare del "tu", mai usare espressioni informali come "scusami" o "puoi").
{channel_rules}"""

CHANNEL_RULES = {
    "chat": "8. Canale CHAT: puoi usare elenchi puntati brevi; niente tabelle.",
    "voice": (
        "8. Canale VOCALE (CHIAMATA TELEFONICA CON IL RISTORANTE): "
        "Risposte STRINGENTI, ESSENZIALI, DIRETTE E CHIARISSIME (massimo 1 o 2 frasi concise, circa 20-25 parole). "
        "Vai subito al punto senza preamboli inutili o convenevoli prolissi. "
        "Fai UNA SOLA domanda mirata alla volta per guidare la prenotazione passo dopo passo (persone -> giorno -> orario -> nome e recapito). "
        "Non dare MAI per scontato il giorno: chiedi sempre per quale giorno desidera il tavolo se non specificato dal cliente. "
        "Se c'è disponibilità, chiedi subito il dato successivo (es: 'Tavolo per 4 alle 20 e 30 disponibile. A quale nome e recapito telefonico confermo?'). "
        "Quando confermi la prenotazione, sii stringente: 'Prenotazione confermata per 4 persone domani alle 20 e 30 a nome Rossi. Il suo codice è 4 8 2 1 0 9. A presto.' "
        "NIENTE elenchi puntati, niente markdown, niente emoji o simboli. "
        "Scrivi gli orari come '20 e 30' (senza due punti) e i codici di prenotazione cifra per cifra con spazi (es: '4 8 2 1 0 9'). "
        "Per domande sul menu o informazioni, rispondi con una sola frase essenziale (max 2 piatti consigliati) senza dilungarti."
    ),
}

FALLBACK_REPLY = "Mi scusi, non sono riuscito a completare la richiesta. Può ripetere in altro modo?"

_LEAKED_CODE_RE = re.compile(
    r"""(?xi)
    (?:^|\b)(?:call:)?(?:create_reservation|check_availability|get_reservation|modify_reservation|cancel_reservation|get_menu|get_restaurant_info)\b(?:\s*\(?[^\n]*\)?|\s*\{[^\}]*\})?
    |\{[^{}]*"(?:customer_name|party_size|date|time|contact|code|arguments|function|name)"[^{}]*\}
    |```(?:json|python)?[\s\S]*?```
    |<\/?tool_call>
    |<function=[^>]*>[\s\S]*?<\/function>
    |<parameter=[^>]*>[\s\S]*?<\/parameter>
    """
)


def sanitize_assistant_reply(text: str, actions: list[dict], channel: str = "chat", is_intermediate: bool = False) -> str:
    """Rimuove qualsiasi sintassi tecnica (funzioni, json, graffe, parametri) dal testo per l'utente.
    Se il modello ha restituito SOLO codice o chiamate a strumenti senza testo colloquiale,
    sintetizza una risposta naturale ed esaustiva basandosi sui risultati degli strumenti eseguiti.
    """
    if not text:
        text = ""

    # Rimuovi tag think di ragionamento
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)

    # Rimuovi qualsiasi frammento di codice o tool calling
    cleaned = _LEAKED_CODE_RE.sub("", text)
    # Pulizia di doppie parentesi graffe o chiavi JSON rimaste
    cleaned = re.sub(r'[\{\}\[\]"]*(?:customer_name|party_size|date|time|contact|code)\s*[:=][^,\n\}]+', "", cleaned)
    cleaned = re.sub(r'\{[^{}]*\}', "", cleaned)
    cleaned = re.sub(r'```', '', cleaned)
    cleaned = re.sub(r'[ \t]+', ' ', cleaned)
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned).strip()

    # Se dopo la rimozione c'è ancora un testo significativo (almeno 8 caratteri alfabetici), usalo
    has_substantive_text = len(re.findall(r"[a-zA-ZÀ-ÿ0-9]", cleaned)) >= 8

    if has_substantive_text:
        return cleaned

    if is_intermediate:
        return ""

    # Se non c'è testo naturale, sintetizziamo la risposta a partire dalle azioni intraprese
    successful_actions = [a for a in actions if a.get("ok")]
    failed_actions = [a for a in actions if not a.get("ok")]

    # 1. Se è stata creata una prenotazione con successo
    create_act = next((a for a in reversed(successful_actions) if a.get("tool") == "create_reservation"), None)
    if create_act and create_act.get("result"):
        res = create_act["result"]
        code = str(res.get("codice", ""))
        nome = res.get("nome", "")
        persone = res.get("persone", "")
        giorno = res.get("giorno") or res.get("data", "")
        ora = res.get("ora", "")
        spaced_code = " ".join(list(code))

        if channel == "voice":
            ora_v = str(ora).replace(":", " e ")
            return (
                f"Prenotazione confermata per {persone} persone a nome {nome} per {giorno} alle {ora_v}. "
                f"Il suo codice di prenotazione è {spaced_code}. "
                f"La ringraziamo e a presto al Ristorante Zio Pierino!"
            )
        return (
            f"Gentile {nome}, la sua prenotazione per {persone} persone per {giorno} alle {ora} è confermata con successo!\n\n"
            f"Il suo codice di prenotazione è: **{code}**\n\n"
            f"La preghiamo di conservare questo codice per eventuali modifiche o per la cancellazione del tavolo. A presto al Ristorante Zio Pierino!"
        )

    # 2. Se è stata verificata la disponibilità
    check_act = next((a for a in reversed(successful_actions) if a.get("tool") == "check_availability"), None)
    if check_act and check_act.get("result"):
        res = check_act["result"]
        if res.get("disponibile"):
            if channel == "voice":
                return "Tavolo disponibile. A quale nome e recapito telefonico desidera confermare la prenotazione?"
            return "Il tavolo per la data e l'orario richiesti è disponibile. A quale nome e recapito telefonico desidera intestare la prenotazione?"
        else:
            alt = res.get("alternative") or []
            if alt:
                alt_str = ", ".join(alt)
                if channel == "voice":
                    return f"Per quell'orario non abbiamo tavoli liberi. Ci sono posti disponibili alle {alt_str.replace(':', ' e ')}. Quale orario preferisce?"
                return f"Purtroppo per l'orario richiesto non abbiamo disponibilità. Abbiamo però tavoli liberi alle: **{alt_str}**. Desidera uno di questi orari?"
            else:
                return "Mi scusi, ma per la data richiesta il ristorante è al completo o chiuso. Desidera verificare un'altra data?"

    # 3. Se ci sono state azioni fallite con errore
    if failed_actions:
        last_err = failed_actions[-1].get("error") or "Non è stato possibile completare l'operazione."
        return f"Mi scusi, si è verificato un problema: {last_err}"

    # 4. Fallback sicuro
    return FALLBACK_REPLY


def build_system_prompt(channel: str, now: datetime | None = None) -> str:
    now = now or datetime.now()
    today = now.date()
    calendar = "\n".join(
        f"- {WEEKDAYS_IT[d.weekday()]} {d.isoformat()}" + (" (oggi)" if i == 0 else " (domani)" if i == 1 else "")
        + (" - CHIUSO" if d.weekday() in db.CLOSED_WEEKDAYS else "")
        for i, d in ((i, today + timedelta(days=i)) for i in range(15))
    )
    return SYSTEM_PROMPT.format(
        today=f"{WEEKDAYS_IT[today.weekday()]} {today.isoformat()}",
        now=now.strftime("%H:%M"),
        year=today.year,
        calendar=calendar,
        channel_rules=CHANNEL_RULES.get(channel, CHANNEL_RULES["chat"]),
    )


@dataclass
class Session:
    history: list[dict] = field(default_factory=list)
    last_seen: float = field(default_factory=time.time)
    lock: threading.Lock = field(default_factory=threading.Lock)


class SessionStore:
    """Memoria delle conversazioni (in RAM, con scadenza per inattività)."""

    def __init__(self):
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()

    def get(self, session_id: str) -> Session:
        with self._lock:
            self._expire()
            session = self._sessions.setdefault(session_id, Session())
            session.last_seen = time.time()
            return session

    def reset(self, session_id: str) -> bool:
        with self._lock:
            return self._sessions.pop(session_id, None) is not None

    def _expire(self) -> None:
        limit = time.time() - config.SESSION_TTL_MINUTES * 60
        for sid in [s for s, sess in self._sessions.items() if sess.last_seen < limit]:
            del self._sessions[sid]


def _trim(history: list[dict]) -> list[dict]:
    """Tiene gli ultimi messaggi, tagliando sempre all'inizio di un turno utente."""
    if len(history) <= config.SESSION_MAX_MESSAGES:
        return history
    cut = len(history) - config.SESSION_MAX_MESSAGES
    while cut < len(history) and history[cut]["role"] != "user":
        cut += 1
    return history[cut:]


def _parse_args(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, json.JSONDecodeError):
        return {}


class Agent:
    def __init__(self, llm: OllamaClient, sessions: SessionStore | None = None):
        self.llm = llm
        self.sessions = sessions or SessionStore()

    def handle(self, session_id: str, user_message: str, channel: str = "chat") -> dict:
        session = self.sessions.get(session_id)
        with session.lock:  # un messaggio alla volta per sessione
            working = _trim(session.history + [{"role": "user", "content": user_message}])
            actions = []
            conn = db.connect()
            try:
                reply = None
                for _ in range(config.LLM_MAX_TOOL_ROUNDS):
                    messages = [{"role": "system", "content": build_system_prompt(channel)}] + working
                    msg = self.llm.chat(messages, TOOLS)
                    tool_calls = msg.get("tool_calls") or []

                    # Se create_reservation è già stata eseguita con successo in questo turno,
                    # non permettiamo una seconda esecuzione duplicata
                    if any(a.get("tool") == "create_reservation" and a.get("ok") for a in actions):
                        tool_calls = [c for c in tool_calls if c.get("function", {}).get("name") != "create_reservation"]

                    if not tool_calls:
                        raw_reply = msg.get("content") or ""
                        reply = sanitize_assistant_reply(raw_reply, actions, channel)
                        working.append({"role": "assistant", "content": reply})
                        break

                    clean_intermediate = sanitize_assistant_reply(msg.get("content", ""), actions, channel, is_intermediate=True)
                    working.append({"role": "assistant", "content": clean_intermediate, "tool_calls": tool_calls})
                    for call in tool_calls:
                        fn = call.get("function", {})
                        name, args = fn.get("name", ""), _parse_args(fn.get("arguments"))

                        # Controllo di sicurezza: se viene invocata check_availability o create_reservation
                        # verifichiamo che il cliente abbia effettivamente indicato una data nella conversazione!
                        if name in ("check_availability", "create_reservation"):
                            active_msgs = working
                            for idx, m in enumerate(working):
                                if m.get("role") == "tool" and m.get("tool_name") == "create_reservation":
                                    active_msgs = working[idx + 1:]
                            user_msgs = [m.get("content", "") for m in active_msgs if m.get("role") == "user"]
                            target_d, _, _, _, _ = _parse_booking_details(user_msgs)
                            if target_d is None:
                                err_msg = (
                                    "ERRORE TASSATIVO: Il cliente non ha ancora specificato per quale giorno o data desidera prenotare! "
                                    "È severamente vietato inventare, presumere o dare per scontata una data (come oggi o domani). "
                                    "Chiedi subito ed espressamente al cliente: 'Per quale giorno desidera prenotare il tavolo?'."
                                )
                                log.warning("Bloccata chiamata a %s senza data fornita dall'utente (args=%s)", name, args)
                                actions.append({"tool": name, "arguments": args, "ok": False, "error": err_msg})
                                working.append({"role": "tool", "tool_name": name, "content": to_json({"ok": False, "errore": err_msg})})
                                continue

                        result = execute_tool(conn, name, args, channel) if name in TOOL_NAMES else \
                            {"ok": False, "errore": f"Strumento sconosciuto: {name}"}
                        log.info("⚙️ [STRUMENTO ESEGUITO]: %s(%s) -> ok=%s", name, args, result["ok"])
                        actions.append({
                            "tool": name,
                            "arguments": args,
                            "ok": result["ok"],
                            "result": result.get("risultato"),
                            "error": result.get("errore")
                        })
                        working.append({"role": "tool", "tool_name": name, "content": to_json(result)})
                if reply is None:
                    reply = sanitize_assistant_reply("", actions, channel)
                    working.append({"role": "assistant", "content": reply})

                # Se non è stata eseguita una create_reservation con successo, ma il modello afferma che la prenotazione
                # è confermata o l'utente ha confermato tutti i dati necessari, eseguiamo noi la creazione per evitare
                # che l'assistente allucini codici fittizi o dimentichi di inserire la prenotazione nel DB!
                has_created = any(a.get("tool") == "create_reservation" and a.get("ok") for a in actions)
                if not has_created:
                    claims_confirmation = bool(re.search(r"\b(?:confermat[ao]|codice(?:\s+di)?\s+prenotazione)\b", reply, re.I))
                    user_confirming = any(re.search(r"\b(?:s[iì]|confermo|conferma|procedi|prenota|va bene|perfetto|d'accordo)\b", m.get("content", ""), re.I) for m in working if m.get("role") == "user")
                    if claims_confirmation or user_confirming:
                        active_msgs = working
                        for idx, m in enumerate(working):
                            if m.get("role") == "tool" and m.get("tool_name") == "create_reservation":
                                active_msgs = working[idx + 1:]
                        user_msgs = [m.get("content", "") for m in active_msgs if m.get("role") == "user"]
                        target_d, time_str, party, name, phone = _parse_booking_details(user_msgs)
                        if target_d and time_str and party and name and phone:
                            args = {
                                "date": target_d.isoformat(),
                                "time": time_str,
                                "party_size": party,
                                "customer_name": name,
                                "contact": phone,
                                "notes": "",
                            }
                            res = execute_tool(conn, "create_reservation", args, channel)
                            if res.get("ok"):
                                actions.append({
                                    "tool": "create_reservation",
                                    "arguments": args,
                                    "ok": True,
                                    "result": res.get("risultato"),
                                    "error": None
                                })
                                reply = sanitize_assistant_reply("", actions, channel)
                                working[-1] = {"role": "assistant", "content": reply}
            finally:
                conn.close()
            session.history = _trim(working)
            return {"session_id": session_id, "reply": reply, "actions": actions}


