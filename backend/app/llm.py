"""Client minimale per l'LLM locale servito da Ollama (API HTTP /api/chat)."""
from __future__ import annotations

import json
import logging
import re

import httpx

from . import config

log = logging.getLogger("backend.llm")


class LLMError(Exception):
    pass


class OllamaClient:
    def __init__(self, base_url: str = config.OLLAMA_URL, model: str = config.LLM_MODEL):
        self.base_url = base_url
        self.model = model
        self._http = httpx.Client(timeout=httpx.Timeout(config.LLM_TIMEOUT, connect=5))

    def available_models(self) -> list[str]:
        try:
            r = self._http.get(f"{self.base_url}/api/tags")
            r.raise_for_status()
            return [m["name"] for m in r.json().get("models", [])]
        except httpx.HTTPError as exc:
            if config.LLM_FALLBACK_MOCK or self.model.lower() in ("mock", "fake", "demo"):
                log.info("Ollama offline su %s, fallback su Mock LLM integrato", self.base_url)
                return ["mock:latest"]
            raise LLMError(f"Ollama non raggiungibile su {self.base_url}: {exc}") from exc

    def resolve_model(self) -> str:
        """Verifica che il modello configurato esista; altrimenti usa il primo disponibile."""
        if self.model.lower() in ("mock", "fake", "demo"):
            self.model = "mock:latest"
            return self.model
        models = self.available_models()
        if not models:
            raise LLMError("Nessun modello installato in Ollama (eseguire: ollama pull qwen2.5:7b).")
        if "mock:latest" in models and len(models) == 1:
            self.model = "mock:latest"
            return self.model
        wanted = self.model if ":" in self.model else f"{self.model}:latest"
        if wanted not in models and self.model not in models:
            log.warning("Modello '%s' non trovato in Ollama, uso '%s'. Disponibili: %s",
                        self.model, models[0], models)
            self.model = models[0]
        return self.model

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        if self.model.startswith("mock"):
            return _mock_chat(messages, tools)
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "keep_alive": "30m",
            "options": {"temperature": config.LLM_TEMPERATURE},
        }
        if tools:
            payload["tools"] = tools
        try:
            r = self._http.post(f"{self.base_url}/api/chat", json=payload)
        except httpx.HTTPError as exc:
            if config.LLM_FALLBACK_MOCK:
                log.warning("Ollama non risponde (%s), rispondo con il Mock LLM di test", exc)
                return _mock_chat(messages, tools)
            raise LLMError(f"Ollama non raggiungibile: {exc}") from exc
        if r.status_code != 200:
            if config.LLM_FALLBACK_MOCK:
                log.warning("Errore Ollama %d, fallback su Mock LLM", r.status_code)
                return _mock_chat(messages, tools)
            raise LLMError(f"Errore Ollama {r.status_code}: {r.text[:300]}")
        return normalize_message(r.json().get("message", {}))


WEEKDAYS_IT = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]


def _describe_date(d) -> str:
    s = d.strftime("%d/%m/%Y")
    return f"{WEEKDAYS_IT[d.weekday()]} {s}"


BOOKING_BLACKLIST = (
    # Saluti e convenevoli
    "ciao", "salve", "buongiorno", "buonasera", "buondi", "buondì", "hey", "hi", "hello", "arrivederci", "addio",
    "grazie", "grazie mille", "prego", "per favore", "per piacere", "cortesemente", "volentieri",
    "ok", "va bene", "perfetto", "ottimo", "chiaro", "d'accordo", "bene", "esatto", "giusto", "si", "no", "non",
    # Prenotazioni e ristorante
    "tavolo", "tavoli", "posto", "posti", "prenotare", "prenotazione", "prenotazioni", "prenoto", "prenotaijne",
    "prenotaiizne", "prenota", "riserva", "riservare", "ristorante", "girasole", "pierino", "zio pierino", "coperto", "conto", "carta",
    "menu", "menù", "piatto", "piatti", "primi", "secondi", "dolci", "dolce", "antipasti", "vino", "acqua",
    "info", "informazioni", "prezzo", "prezzi", "costo", "costi",
    # Date e orari
    "lunedì", "lunedi", "martedì", "martedi", "mercoledì", "mercoledi", "giovedì", "giovedi", "venerdì", "venerdi", "sabato", "domenica",
    "oggi", "domani", "dopodomani", "stasera", "sera", "cena", "pranzo", "mezzogiorno", "mezzanotte", "alle", "ore", "orario", "orari",
    "giorno", "data", "chiuso", "aperto", "chiusura", "apertura",
    "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre",
    "gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic",
    # Numeri a parole
    "uno", "una", "un", "due", "tre", "quattro", "cinque", "sei", "sette", "otto", "nove", "dieci",
    # Parole comuni e verbi
    "in", "per", "con", "senza", "da", "di", "a", "su", "tra", "fra",
    "vorrei", "voglio", "volgio", "desidero", "posso", "potrei", "siamo", "saremo", "saremmo",
    "telefono", "cellulare", "numero", "recapito", "contatto", "annulla", "cancella", "modifica"
)


def _parse_booking_details(user_messages: list[str], last_bot_msg: str = "", messages: list[dict] | None = None):
    from datetime import date, timedelta

    party = None
    target_d = None
    time_str = None
    name = None
    phone = None
    today = date.today()

    party_words = {
        "uno": 1, "una": 1, "un": 1, "due": 2, "tre": 3, "quattro": 4, "cinque": 5,
        "sei": 6, "sette": 7, "otto": 8, "nove": 9, "dieci": 10
    }
    weekdays = {
        "lunedì": 0, "lunedi": 0, "martedì": 1, "martedi": 1, "mercoledì": 2, "mercoledi": 2,
        "giovedì": 3, "giovedi": 3, "venerdì": 4, "venerdi": 4, "sabato": 5, "domenica": 6,
    }

    clean_last_b = re.sub(r"[*_`#]", "", (last_bot_msg or "")).lower()
    is_asking_time = any(k in clean_last_b for k in ("a che ora", "orario", "ora desidera", "turni di prenotazione", "ore 12", "ore 19"))
    is_asking_party = any(k in clean_last_b for k in ("quante persone", "quanti ospiti", "quanti posti"))
    is_asking_date = any(k in clean_last_b for k in ("quale giorno", "quale data", "per quando", "giorno desidera"))
    is_asking_name = any(k in clean_last_b for k in ("quale nome", "a che nome", "a quale nome", "nome dobbiamo", "nome desidera", "intestar", "suo nome", "a nome di chi", "nome"))

    # 1. Cerca il recapito telefonico da tutti i messaggi
    for msg in reversed(user_messages):
        m_tel_mask = re.search(r"(\[TEL_[^\]]+\])", msg)
        if m_tel_mask:
            phone = m_tel_mask.group(1)
            break
        m_kw = re.search(
            r"(?:tel(?:efono)?|cell(?:ulare)?|numero(?:\s+di\s+telefono)?|contatto|recapito)\s*(?:è|e'|:)?\s*([+]?\d[\d\s.-]{7,15}\d)",
            msg, re.I
        )
        if m_kw:
            cand = m_kw.group(1).strip()
            digits = re.sub(r"\D", "", cand)
            if 8 <= len(digits) <= 13:
                phone = cand
                break
        if not re.search(r"\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}", msg):
            m_pure = re.search(r"(?<!\w)([+]?\d[\d\s.-]{7,15}\d)(?!\w)", msg)
            if m_pure:
                cand = m_pure.group(1).strip()
                digits = re.sub(r"\D", "", cand)
                if 8 <= len(digits) <= 13:
                    phone = cand
                    break

    # 2. Cerca il nome da tutti i messaggi
    # 2a. Segnaposto privacy
    for msg in reversed(user_messages):
        m_mask = re.search(r"(\[NOME_[^\]]+\])", msg)
        if m_mask:
            name = m_mask.group(1)
            break

    # 2b. Formule esplicite di presentazione ("a nome Mario", "mi chiamo Luca", "il mio nome è...", "sono Marco")
    if not name:
        for msg in reversed(user_messages):
            m_name = re.search(r"(?:a nome(?: di)?|per conto di|mi chiamo|il mio nome è|il nome è|nome:\s*|sono)\s+([A-Za-zÀ-ÿ]+(?:\s+[A-Za-zÀ-ÿ]+)?)", msg, re.I)
            if m_name:
                cand = m_name.group(1).strip()
                words = cand.lower().split()
                if not any(w in BOOKING_BLACKLIST for w in words):
                    name = cand
                    break

    # 2c. Se abbiamo l'intera cronologia di 'messages', cerchiamo la risposta dell'utente alla specifica domanda sul nome del bot
    if not name and messages:
        for idx in range(len(messages) - 1, 0, -1):
            curr = messages[idx]
            prev = messages[idx - 1]
            if curr.get("role") == "user" and prev.get("role") == "assistant":
                prev_text = re.sub(r"[*_`#]", "", prev.get("content", "")).lower()
                if any(k in prev_text for k in ("quale nome", "a che nome", "a quale nome", "nome dobbiamo", "nome desidera", "intestar", "suo nome")):
                    cand = curr.get("content", "").strip()
                    cand_clean = re.sub(r"^[^\w]+|[^\w]+$", "", cand)
                    words = cand_clean.lower().split()
                    if 1 <= len(words) <= 3 and not any(w in BOOKING_BLACKLIST for w in words):
                        name = cand_clean
                        break

    # 2d. Se il bot sta chiedendo il nome adesso (ultimo turno) e l'utente ha risposto con testo puro
    if not name and is_asking_name and user_messages:
        latest = user_messages[-1].strip()
        cand_clean = re.sub(r"^[^\w]+|[^\w]+$", "", latest)
        words = cand_clean.lower().split()
        if 1 <= len(words) <= 3 and not any(w in BOOKING_BLACKLIST for w in words):
            name = cand_clean

    # 2e. Nome proprio completo (es. 'Mario Rossi') presente nei messaggi, escludendo saluti o comandi
    if not name:
        for msg in reversed(user_messages):
            t = msg.strip()
            words = t.split()
            # Nome e cognome: 2 parole di sole lettere, entrambe con iniziale maiuscola
            if 2 <= len(words) <= 3 and all(re.match(r"^[A-ZÀ-Ý][a-zà-ÿ]+$", w) for w in words):
                if not any(w.lower() in BOOKING_BLACKLIST for w in words):
                    name = t
                    break

    # 3. Cerca orario procedendo a ritroso (prima delle persone per evitare che ore come 12 siano scambiate per persone)
    minute_words = {
        "mezza": 30, "mezzo": 30, "trenta": 30,
        "quindici": 15, "un quarto": 15,
        "quarantacinque": 45, "tre quarti": 45,
        "zero zero": 0, "in punto": 0
    }
    for i, msg in enumerate(reversed(user_messages)):
        ml = msg.lower()
        is_latest_user_msg = (i == 0)

        # 12:00, 20:30, 00:00
        m_time = re.search(r"\b([01]?\d|2[0-3])[:.]([0-5]\d)\b", ml)
        if m_time:
            time_str = f"{int(m_time.group(1)):02d}:{m_time.group(2)}"
            break

        # 20 e 30, 20 e mezza
        m_spoken = re.search(r"\b(?:alle|ore|verso le)?\s*([01]?\d|2[0-3])\s+e\s+(trenta|mezza|mezzo|quindici|un quarto|quarantacinque|tre quarti|\d{1,2})\b", ml)
        if m_spoken:
            h = int(m_spoken.group(1))
            min_val = m_spoken.group(2)
            mm = minute_words.get(min_val, int(min_val) if min_val.isdigit() else 0)
            if 7 <= h <= 11 and ("sera" in ml or "cena" in ml):
                h += 12
            elif 1 <= h <= 3 and ("pranzo" in ml or "pomeriggio" in ml):
                h += 12
            time_str = f"{h:02d}:{mm:02d}"
            break

        # alle 12, verso le 20
        m_hour = re.search(r"\b(?:alle|ore|verso le)\s*([01]?\d|2[0-3])\b", ml)
        if m_hour:
            h = int(m_hour.group(1))
            if 7 <= h <= 11 and ("sera" in ml or "cena" in ml):
                h += 12
            elif 1 <= h <= 3 and ("pranzo" in ml or "pomeriggio" in ml):
                h += 12
            time_str = f"{h:02d}:00"
            break

        # Parole chiave per orario
        if "mezzogiorno" in ml:
            time_str = "12:00"
            break
        if "mezzanotte" in ml:
            time_str = "00:00"
            break
        if "a pranzo" in ml:
            time_str = "13:00"
            break
        if "a cena" in ml or "stasera" in ml:
            time_str = "20:30"
            break

        # Espressioni per le 13:00 / 13:30 con "l'una", "all'una", "verso l'una"
        m_una_min = re.search(r"\b(?:all['’]|verso\s+l['’]|l['’])una\s+e\s+(mezza|mezzo|trenta|\d{1,2})\b", ml)
        if m_una_min:
            min_val = m_una_min.group(1)
            mm = minute_words.get(min_val, int(min_val) if min_val.isdigit() else 30)
            time_str = f"13:{mm:02d}"
            break
        if re.search(r"\b(?:all['’]|verso\s+l['’]|l['’])una\b", ml):
            time_str = "13:00"
            break

        # Singolo numero orario (es. "12", "13", "14", "19", "20", "21", "22" o qualunque numero se il bot stava chiedendo l'orario)
        m_single_hour = re.match(r"^\s*([01]?\d|2[0-3])\s*$", ml)
        if m_single_hour:
            h = int(m_single_hour.group(1))
            if (12 <= h <= 14) or (19 <= h <= 22):
                time_str = f"{h:02d}:00"
                break
            if is_asking_time and is_latest_user_msg:
                if 7 <= h <= 11 and ("sera" in ml or "cena" in ml):
                    h += 12
                elif 1 <= h <= 3 and ("pranzo" in ml or "pomeriggio" in ml):
                    h += 12
                time_str = f"{h:02d}:00"
                break

    # 4. Cerca data/giorno procedendo a ritroso (prima delle persone per evitare che giorni come 29 siano scambiati per persone)
    months_it = {
        "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4, "maggio": 5, "giugno": 6,
        "luglio": 7, "agosto": 8, "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12,
        "gen": 1, "feb": 2, "mar": 3, "apr": 4, "mag": 5, "giu": 6,
        "lug": 7, "ago": 8, "set": 9, "ott": 10, "nov": 11, "dic": 12,
    }

    date_matched_day = None

    for msg in reversed(user_messages):
        ml = msg.lower()
        if "stasera" in ml or "oggi" in ml:
            target_d = today
            date_matched_day = today.day
            break
        if "dopodomani" in ml:
            target_d = today + timedelta(days=2)
            date_matched_day = target_d.day
            break
        if "domani" in ml:
            target_d = today + timedelta(days=1)
            date_matched_day = target_d.day
            break

        # Data con nome mese (es. "29 ottobre", "29 ott", "29 di ottobre", "primo novembre", "1° novembre")
        m_named = re.search(
            r"\b(\d{1,2}|primo|1°)\s*(?:di\s+)?(gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|settembre|ottobre|novembre|dicembre|gen|feb|mar|apr|mag|giu|lug|ago|set|ott|nov|dic)\b(?:\s+(\d{4}))?",
            ml
        )
        if m_named:
            d_raw = m_named.group(1)
            day_val = 1 if d_raw in ("primo", "1°") else int(d_raw)
            m_raw = m_named.group(2)
            month_val = months_it.get(m_raw, today.month)
            year_val = int(m_named.group(3)) if m_named.group(3) else today.year
            try:
                cand_d = date(year_val, month_val, day_val)
                if cand_d < today and not m_named.group(3):
                    cand_d = date(year_val + 1, month_val, day_val)
                target_d = cand_d
                date_matched_day = day_val
                break
            except ValueError:
                pass

        # Data numerica IT (es. 15/10, 15/10/2026, 15-10, 15.10)
        m_it = re.search(r"\b(\d{1,2})[/.-](\d{1,2})(?:[/.-](202\d))?\b", ml)
        if m_it:
            try:
                day_val = int(m_it.group(1))
                month_val = int(m_it.group(2))
                year_val = int(m_it.group(3)) if m_it.group(3) else today.year
                target_d = date(year_val, month_val, day_val)
                date_matched_day = day_val
                break
            except ValueError:
                pass

        # Data ISO (es. 2026-10-15)
        m_iso = re.search(r"\b(202\d-\d{2}-\d{2})\b", ml)
        if m_iso:
            try:
                target_d = date.fromisoformat(m_iso.group(1))
                date_matched_day = target_d.day
                break
            except ValueError:
                pass

        # Relativo (es. "tra 2 giorni", "tra due giorni", "tra tre giorni")
        m_rel_days = re.search(r"\btra\s+(\d+|due|tre|quattro|cinque|sei|sette)\s+giorni\b", ml)
        if m_rel_days:
            raw_n = m_rel_days.group(1)
            num_map = {"due": 2, "tre": 3, "quattro": 4, "cinque": 5, "sei": 6, "sette": 7}
            n_days = int(raw_n) if raw_n.isdigit() else num_map.get(raw_n, 0)
            if n_days > 0:
                target_d = today + timedelta(days=n_days)
                date_matched_day = target_d.day
                break

        # Giorno della settimana (es. venerdì, mercoledì)
        found_w = False
        for w_str, w_num in weekdays.items():
            if re.search(rf"\b{w_str}\b", ml):
                diff = (w_num - today.weekday()) % 7
                if diff == 0:
                    diff = 7 if "prossim" in ml else 0
                elif "prossim" in ml and diff < 4:
                    diff += 7
                target_d = today + timedelta(days=diff)
                date_matched_day = target_d.day
                found_w = True
                break
        if found_w:
            break

        # Giorno del mese con prefisso esplicito "il / per il / giorno / per il giorno" (es. "per il 29", "il 29", "il giorno 29", "giorno 29")
        m_day_explicit = re.search(r"\b(?:per\s+il|il|per\s+il\s+giorno|il\s+giorno|giorno|per\s+giorno)\s+([1-9]|[12]\d|3[01]|primo|1°)\b", ml)
        if m_day_explicit:
            raw_d = m_day_explicit.group(1)
            val = 1 if raw_d in ("primo", "1°") else int(raw_d)
            try:
                mo = today.month
                yr = today.year
                if val < today.day:
                    mo += 1
                    if mo > 12:
                        mo = 1
                        yr += 1
                target_d = date(yr, mo, val)
                date_matched_day = val
                break
            except ValueError:
                pass

        # Giorno del mese con "prenotare per 29", "per 29", "tavolo per 29" (es. 11..31 senza "persone")
        # In italiano "prenotare per 29" indica il giorno del mese (le prenotazioni online arrivano a max 10 persone).
        m_per_day = re.search(r"\b(?:prenotare\s+per|prenoto\s+per|vorrei\s+prenotare\s+per|volgio\s+prenotare\s+per|voglio\s+prenotare\s+per|tavolo\s+per|per)\s+([1-9]|[12]\d|3[01])\b", ml)
        if m_per_day:
            val = int(m_per_day.group(1))
            after_match = ml[m_per_day.end():]
            if not re.match(r"^\s*(?:persone|posti|ospiti)\b", after_match):
                if val > 10 or is_asking_date:
                    try:
                        mo = today.month
                        yr = today.year
                        if val < today.day:
                            mo += 1
                            if mo > 12:
                                mo = 1
                                yr += 1
                        target_d = date(yr, mo, val)
                        date_matched_day = val
                        break
                    except ValueError:
                        pass

        # Giorno del mese se il bot stava chiedendo la data (es. "15", "il 15", "29")
        if is_asking_date and not re.search(r"[:.]", ml) and not re.search(r"\b(?:alle|ore|verso le)\b", ml) and not any(k in ml for k in ("persona", "persone", "posti", "ospiti")):
            m_day = re.search(r"\b([1-9]|[12]\d|3[01])\b", ml)
            if m_day:
                val = int(m_day.group(1))
                try:
                    mo = today.month
                    yr = today.year
                    if val < today.day:
                        mo += 1
                        if mo > 12:
                            mo = 1
                            yr += 1
                    target_d = date(yr, mo, val)
                    date_matched_day = val
                    break
                except ValueError:
                    pass

    # 5. Cerca persone procedendo a ritroso (il messaggio più recente ha precedenza)
    for i, msg in enumerate(reversed(user_messages)):
        ml = msg.lower()
        is_latest_user_msg = (i == 0)

        # Regola 1: Regole con parola esplicita "persone/posti/ospiti" (es. "4 persone", "tavolo per 2 persone", "per 29 persone")
        m_explicit = re.search(r"\b(\d{1,2})\s*(?:persone|posti|ospiti)\b", ml)
        if m_explicit:
            party = int(m_explicit.group(1))
            break

        m_explicit_prefix = re.search(r"(?:per|in|siamo|saremo|saremmo|tavolo da|tavolo per)(?:\s+in)?\s*(\d{1,2})\s+(?:persone|posti|ospiti)\b", ml)
        if m_explicit_prefix:
            party = int(m_explicit_prefix.group(1))
            break

        # Regola 2: Parole numeriche per persone (es. "in due", "siamo cinque", "tavolo per quattro", "due persone")
        found_word = False
        for w, n in party_words.items():
            if re.search(rf"\b(?:per|in|siamo|saremo|saremmo|tavolo da|tavolo per)(?:\s+in)?\s+{w}\b", ml) or re.search(rf"\b{w}\s+(?:persone|posti|ospiti)\b", ml):
                party = n
                found_word = True
                break
        if found_word:
            break

        if ml.strip() in party_words:
            if not (is_latest_user_msg and (is_asking_time or is_asking_date)):
                party = party_words[ml.strip()]
                break

        # Regola 3: "siamo 5", "siamo in 5", "saremo 5", "saremmo in 5" (in italiano 'siamo N' indica sempre persone!)
        m_siamo = re.search(r"\b(?:siamo|saremo|saremmo)(?:\s+in)?\s*(\d{1,2})\b", ml)
        if m_siamo:
            val = int(m_siamo.group(1))
            party = val
            break

        # Regola 4: Prefissi "tavolo da 4", "tavolo per 4", "in 4" (senza "persone")
        # Deve essere diverso dal giorno della data ed escludere mesi successivi
        m_phrase = re.search(r"(?:tavolo da|tavolo per|\bin)\s*(\d{1,2})\b", ml)
        if m_phrase:
            val = int(m_phrase.group(1))
            after = ml[m_phrase.end():]
            is_followed_by_month = any(re.match(rf"^\s*(?:di\s+)?{m_name}\b", after) for m_name in months_it.keys())
            if not is_followed_by_month and val != date_matched_day:
                if val <= 10 or not (1 <= val <= 31):
                    party = val
                    break

        # Regola 5: "per <N>" senza "persone" (es. "per 4", "prenotare per 2")
        # Regola cruciale: NON deve essere confuso con date ("per 29", "per 29 ottobre", "per il 29")
        m_per = re.search(r"(?<!\bil\s)(?<!\bgiorno\s)\bper\s+(\d{1,2})\b", ml)
        if m_per:
            val = int(m_per.group(1))
            after = ml[m_per.end():]
            is_followed_by_month = any(re.match(rf"^\s*(?:di\s+)?{m_name}\b", after) for m_name in months_it.keys())
            is_followed_by_time = bool(re.match(r"^\s*(?:[:.]\d{2}|e\s+(?:mezza|mezzo|trenta|\d{1,2}))\b", after))
            if not is_followed_by_month and not is_followed_by_time:
                # Solo se <= 10 e non è il giorno già estratto per la data!
                if val <= 10 and val != date_matched_day:
                    party = val
                    break

        # Regola 6: Singolo numero autonomo o con prefisso di correzione (es. "2", "4", "in 2", "so siamo 5", "no 5", "anzi 5")
        m_single = re.match(r"^\s*(?:no[,.]?|so[,.]?|anzi|invece|scusa|scusi|modifica|cambia)?\s*(?:siamo\s+)?(?:in\s+)?(\d{1,2})\s*$", ml)
        if m_single:
            val = int(m_single.group(1))
            has_corr = bool(re.match(r"^\s*(?:no[,.]?|so[,.]?|anzi|invece|scusa|scusi|modifica|cambia|siamo)\b", ml))
            if is_latest_user_msg and (is_asking_time or is_asking_date) and not has_corr:
                continue
            if val in (12, 13, 14, 19, 20, 21, 22) and not has_corr:
                continue
            if val == date_matched_day:
                continue
            if val <= 10 or is_asking_party or has_corr:
                party = val
                break

    return target_d, time_str, party, name, phone


def _mock_chat(messages: list[dict], tools: list[dict] | None = None) -> dict:
    """Simulatore intelligente dell'LLM per test offline e dimostrazioni con verifica man mano di persone, giorno e orario."""
    last_msg = messages[-1] if messages else {}

    # Se l'ultimo messaggio è il risultato di uno strumento eseguito
    if last_msg.get("role") == "tool":
        tool_name = last_msg.get("tool_name", "")
        try:
            content_json = json.loads(last_msg.get("content", "{}"))
        except Exception:
            content_json = {}

        ok = content_json.get("ok", True)
        res = content_json.get("risultato") if ok else None
        err = content_json.get("errore") or ""

        if not ok and err:
            if "Non è stata indicata nessuna modifica" in err:
                return {
                    "role": "assistant",
                    "content": "La sua prenotazione risulta già confermata con questi dettagli. Se desidera apportare una modifica, mi indichi un orario differente (es. *alle 13:00* o *alle 20:30*), una nuova data o un numero di persone diverso."
                }
            return {
                "role": "assistant",
                "content": f"Mi scusi, si è verificato un inconveniente: {err}. Desidera provare con un'altra data o orario?"
            }

        if tool_name == "get_menu":
            piatti = []
            if isinstance(res, dict):
                for cat, items in res.items():
                    for it in items[:2]:
                        piatti.append(f"{it['piatto']} ({it['prezzo_euro']}€)")
            elenco = ", ".join(piatti) if piatti else "Risotto alla milanese (15€), Tagliata di manzo (24€), Tiramisù (7€)"
            return {
                "role": "assistant",
                "content": f"Ecco alcune proposte dal nostro menu: {elenco}.\nI piatti sono disponibili anche con opzioni vegetariane e senza glutine. Desidera prenotare un tavolo?"
            }

        if tool_name == "get_restaurant_info":
            return {
                "role": "assistant",
                "content": (
                    "Il Ristorante Zio Pierino PSG si trova in **Lungomare Antonio Gramsci 42, 63822 Porto San Giorgio (FM)**.\n\n"
                    "• **Orari di apertura**: dal martedì alla domenica a pranzo (12:00-15:00, ultima prenotazione 14:00) "
                    "e a cena (19:00-23:30, ultima prenotazione 22:00). Lunedì chiuso.\n"
                    "• **Come arrivare**: Sul suggestivo lungomare di Porto San Giorgio, a 5 minuti a piedi dalla stazione FS e dal porto peschereccio; parcheggio adiacente.\n"
                    "• **Contatti**: tel. +39 0734 678910, email: info@ziopierinopsg.it."
                )
            }

        if tool_name == "check_availability":
            user_msgs = [m.get("content", "") for m in messages if m.get("role") == "user"]
            _, _, _, customer_name, customer_phone = _parse_booking_details(user_msgs, messages=messages)

            if isinstance(res, dict) and res.get("disponibile"):
                giorno = res.get("giorno", "")
                ora = res.get("ora", "")
                persone = res.get("persone", "")
                zona = res.get("zona", "sala interna")

                # Se abbiamo già sia nome sia telefono, procediamo subito con create_reservation
                if customer_name and customer_phone:
                    return {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [{
                            "function": {
                                "name": "create_reservation",
                                "arguments": {
                                    "date": res.get("data"),
                                    "time": ora,
                                    "party_size": persone,
                                    "customer_name": customer_name,
                                    "contact": customer_phone,
                                }
                            }
                        }]
                    }

                # Se abbiamo il nome ma manca il telefono, chiediamo il recapito telefonico
                if customer_name and not customer_phone:
                    return {
                        "role": "assistant",
                        "content": (
                            f"Abbiamo verificato la disponibilità: tavolo disponibile per **{persone} persone** "
                            f"per **{giorno}** alle ore **{ora}** ({zona})!\n\n"
                            f"Per completare la prenotazione a nome **{customer_name}**, ci può indicare un **numero di telefono** di recapito?"
                        )
                    }

                # Altrimenti chiediamo prima il nome (e poi il telefono)
                return {
                    "role": "assistant",
                    "content": (
                        f"Abbiamo verificato la disponibilità: tavolo disponibile per **{persone} persone** "
                        f"per **{giorno}** alle ore **{ora}** ({zona})!\n\n"
                        f"Per confermare la prenotazione, a quale **nome** dobbiamo intestarla?"
                    )
                }

            alt = res.get("orari_alternativi_stesso_giorno") or res.get("alternative", []) if isinstance(res, dict) else []
            alt_str = f" Orari alternativi disponibili: **{', '.join(alt)}**." if alt else ""
            return {
                "role": "assistant",
                "content": f"Mi dispiace, ma per l'orario richiesto non abbiamo tavoli disponibili.{alt_str}\nDesidera prenotare per uno di questi orari o per un altro giorno?"
            }

        if tool_name == "create_reservation":
            if isinstance(res, dict):
                code = res.get("codice", "")
                nome = res.get("nome", "Cliente")
                contatto = res.get("contatto", "")
                giorno = res.get("giorno", "")
                data = res.get("data", "")
                ora = res.get("ora", "")
                persone = res.get("persone", "")
                zona = res.get("zona", "")
                tavolo = res.get("tavolo", "")
                tel_line = f"• **Telefono**: {contatto}\n" if contatto else ""
                return {
                    "role": "assistant",
                    "content": (
                        f"Prenotazione confermata con successo!\n\n"
                        f"• **Nome**: {nome}\n"
                        f"{tel_line}"
                        f"• **Persone**: {persone} persone\n"
                        f"• **Giorno**: {giorno or data}\n"
                        f"• **Orario**: ore {ora}\n"
                        f"• **Tavolo**: {tavolo} ({zona})\n"
                        f"• **Codice di prenotazione**: `{code}`\n\n"
                        f"Conservi questo codice di 6 cifre per eventuali modifiche o disdette. La aspettiamo al Ristorante Zio Pierino PSG!"
                    )
                }
            return {"role": "assistant", "content": "Prenotazione confermata con successo! La aspettiamo al Ristorante Zio Pierino PSG."}

        if tool_name == "cancel_reservation":
            code = res.get("codice", "") if isinstance(res, dict) else ""
            code_str = f" `{code}`" if code else ""
            return {"role": "assistant", "content": f"La sua prenotazione{code_str} è stata cancellata correttamente. Restiamo a disposizione per future occasioni!"}

        if tool_name == "get_reservation":
            if isinstance(res, dict):
                code = res.get("codice", "")
                nome = res.get("nome", "Cliente")
                giorno = res.get("giorno", "")
                data = res.get("data", "")
                ora = res.get("ora", "")
                persone = res.get("persone", "")
                zona = res.get("zona", "")
                tavolo = res.get("tavolo", "")
                # Considera solo i messaggi utente successivi all'ultima creazione di prenotazione
                active_msgs = messages
                for idx, m in enumerate(messages):
                    if m.get("role") == "tool" and m.get("tool_name") == "create_reservation":
                        active_msgs = messages[idx + 1:]
                user_msgs = [m.get("content", "") for m in active_msgs if m.get("role") == "user"]
                target_d, time_str, party, _, _ = _parse_booking_details(user_msgs)

                # Se l'utente ha fornito un orario diverso, una data diversa o un numero persone diverso nei messaggi recenti:
                has_different_time = bool(time_str and time_str != ora)
                has_different_date = bool(target_d and target_d.isoformat() != data)
                has_different_party = bool(party and party != persone)

                if has_different_time or has_different_date or has_different_party:
                    args = {"code": code}
                    if has_different_time:
                        args["time"] = time_str
                    if has_different_date:
                        args["date"] = target_d.isoformat()
                    if has_different_party:
                        args["party_size"] = party
                    return {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [{
                            "function": {
                                "name": "modify_reservation",
                                "arguments": args
                            }
                        }]
                    }
                return {
                    "role": "assistant",
                    "content": (
                        f"Ho recuperato la sua prenotazione `{code}`:\n\n"
                        f"• **Nome**: {nome}\n"
                        f"• **Persone**: {persone} persone\n"
                        f"• **Giorno**: {giorno or data}\n"
                        f"• **Orario attuale**: ore {ora}\n"
                        f"• **Tavolo**: {tavolo} ({zona})\n\n"
                        f"Quale modifica desidera apportare? Può indicarmi il nuovo orario (es. *alle 21:00*), la nuova data o il numero di persone."
                    )
                }
            return {"role": "assistant", "content": "Prenotazione trovata. Quale modifica desidera apportare (data, orario o persone)?"}

        if tool_name == "modify_reservation":
            if isinstance(res, dict):
                code = res.get("codice", "")
                nome = res.get("nome", "Cliente")
                giorno = res.get("giorno", "")
                data = res.get("data", "")
                ora = res.get("ora", "")
                persone = res.get("persone", "")
                zona = res.get("zona", "")
                tavolo = res.get("tavolo", "")
                return {
                    "role": "assistant",
                    "content": (
                        f"La prenotazione `{code}` è stata modificata con successo!\n\n"
                        f"• **Nome**: {nome}\n"
                        f"• **Persone**: {persone} persone\n"
                        f"• **Giorno**: {giorno or data}\n"
                        f"• **Nuovo orario**: ore {ora}\n"
                        f"• **Tavolo**: {tavolo} ({zona})\n"
                        f"• **Codice di prenotazione**: `{code}`\n\n"
                        f"I nuovi dettagli sono stati registrati nel sistema. La aspettiamo al Ristorante Zio Pierino PSG!"
                    )
                }
            return {"role": "assistant", "content": "La prenotazione è stata modificata con successo."}

        return {"role": "assistant", "content": "Operazione completata con successo."}

    # Raccogli tutti i messaggi dell'utente per il contesto conversazionale
    user_messages = [m.get("content", "") for m in messages if m.get("role") == "user"]
    latest_user_text = user_messages[-1].strip().lower() if user_messages else ""
    all_user_text = " ".join(user_messages).lower()

    # Ultimo messaggio inviato dal bot per comprendere la risposta dell'utente
    last_bot_msg = ""
    for m in reversed(messages):
        if m.get("role") == "assistant" and m.get("content"):
            last_bot_msg = m.get("content", "").lower()
            break

    # Menu
    if any(k in latest_user_text for k in ("menu", "piatt", "mangiar", "dolc", "prim", "second", "prezz", "cost")):
        return {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "get_menu", "arguments": {}}}]}

    # Info ristorante
    if any(k in latest_user_text for k in ("info", "orari", "dove", "indirizzo", "telefono", "apert", "chiuso", "parcheggi", "contatt")):
        return {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "get_restaurant_info", "arguments": {}}}]}

    all_codes = re.findall(r"\b(\d{6})\b", all_user_text)
    code_match = all_codes[-1] if all_codes else None

    # Se una prenotazione è già stata creata nella cronologia, i messaggi precedenti a create_reservation
    # non devono essere considerati come parametri per una successiva modifica o nuova operazione.
    active_messages = messages
    for idx, m in enumerate(messages):
        if m.get("role") == "tool" and m.get("tool_name") == "create_reservation":
            active_messages = messages[idx + 1:]
    active_user_msgs = [m.get("content", "") for m in active_messages if m.get("role") == "user"]

    # Cancellazione
    if any(k in all_user_text for k in ("cancell", "disdi", "annull")):
        if code_match:
            return {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "cancel_reservation", "arguments": {"code": code_match}}}]}
        return {"role": "assistant", "content": "Per cancellare la prenotazione, mi comunichi per favore il suo codice a 6 cifre rilasciato al momento della conferma."}

    # Modifica o codice prenotazione fornito
    is_modify_intent = any(k in all_user_text for k in ("modific", "cambia", "spost")) or (
        last_bot_msg and any(k in last_bot_msg for k in ("codice a 6 cifre", "modifiche desiderate", "quale modifica desidera apportare"))
    )

    if code_match and (is_modify_intent or not any(k in all_user_text for k in ("vorrei prenotare", "prenotare un tavolo"))):
        mod_user_msgs = active_user_msgs if active_user_msgs else user_messages
        target_d, time_str, party, _, _ = _parse_booking_details(mod_user_msgs, last_bot_msg, messages=active_messages)
        has_gotten_res = any(m.get("role") == "tool" and m.get("tool_name") == "get_reservation" for m in active_messages)
        if has_gotten_res and (time_str or target_d or party):
            args = {"code": code_match}
            if time_str:
                args["time"] = time_str
            if target_d:
                args["date"] = target_d.isoformat()
            if party:
                args["party_size"] = party
            return {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "modify_reservation", "arguments": args}}]}
        elif not has_gotten_res:
            return {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "get_reservation", "arguments": {"code": code_match}}}]}
        else:
            return {
                "role": "assistant",
                "content": f"Per modificare la prenotazione `{code_match}`, mi indichi per favore il nuovo orario (es. *alle 20:30*), la nuova data o il numero di persone desiderato."
            }

    if is_modify_intent and not code_match:
        return {"role": "assistant", "content": "Per modificare la prenotazione, mi indichi per favore il codice a 6 cifre della prenotazione e le modifiche desiderate (es. *cambio orario alle 21:00*)."}

    # Flusso di prenotazione tavolo: guidato man mano passo dopo passo
    is_booking_intent = any(k in all_user_text for k in ("prenot", "tavolo", "posto", "riserv", "cenare", "pranzare")) or (
        last_bot_msg and any(k in last_bot_msg for k in ("persone", "giorno", "orario", "ora", "nome", "telefono", "cellulare", "recapito", "tavolo"))
    )

    if is_booking_intent:
        from datetime import date, timedelta
        target_d, time_str, party, name, phone = _parse_booking_details(user_messages, last_bot_msg, messages=messages)

        # ----------------- PASSO 1: NUMERO DI PERSONE -----------------
        # Verifica persone se fornite
        if party is not None:
            if party < 1:
                return {
                    "role": "assistant",
                    "content": "Il tavolo deve essere per almeno **1 persona**. Per quante persone desidera prenotare?"
                }
            if party > 10:
                return {
                    "role": "assistant",
                    "content": (
                        "Sul sito è possibile prenotare online per un massimo di **10 persone**.\n"
                        "Per gruppi superiori a 10 ospiti vi invitiamo a contattare telefonicamente il ristorante al numero **+39 02 1234 5678**.\n\n"
                        "Per quanti ospiti desidera prenotare online (da 1 a 10)?"
                    )
                }

        # Verifica giorno se già fornito
        if target_d is not None:
            today = date.today()
            if target_d < today:
                return {
                    "role": "assistant",
                    "content": f"La data indicata ({_describe_date(target_d)}) è già passata. **Per quale giorno futuro** desidera prenotare?"
                }
            if target_d.weekday() == 0:
                return {
                    "role": "assistant",
                    "content": f"Il Ristorante Zio Pierino PSG è **chiuso il lunedì** ({_describe_date(target_d)}). Siamo aperti dal martedì alla domenica sia a pranzo che a cena. **Per quale altro giorno** desidera prenotare?"
                }
            if target_d > today + timedelta(days=60):
                return {
                    "role": "assistant",
                    "content": "È possibile prenotare al massimo fino a 60 giorni in anticipo. **Per quale data** desidera prenotare?"
                }

        if party is None:
            if target_d is not None and time_str is not None:
                return {
                    "role": "assistant",
                    "content": f"Certamente! Con piacere la aiutiamo a prenotare per **{_describe_date(target_d)}** alle ore **{time_str}** al Ristorante Zio Pierino PSG.\n\n**Per quante persone** desidera riservare il tavolo?"
                }
            if target_d is not None:
                return {
                    "role": "assistant",
                    "content": f"Certamente! Con piacere la aiutiamo a prenotare per **{_describe_date(target_d)}** al Ristorante Zio Pierino PSG.\n\n**Per quante persone** desidera riservare il tavolo?"
                }
            return {
                "role": "assistant",
                "content": "Certamente! Con piacere la aiutiamo a prenotare un tavolo al Ristorante Zio Pierino PSG.\n\n**Per quante persone** desidera riservare il tavolo?"
            }

        # ----------------- PASSO 2: GIORNO E DATA -----------------
        if target_d is None:
            return {
                "role": "assistant",
                "content": f"Perfetto, tavolo per **{party} persone**!\n\n**Per quale giorno** desidera prenotare? (es. oggi, domani, venerdì 16/10)"
            }

        # ----------------- PASSO 3: ORARIO -----------------
        # Verifica orario se fornito
        if time_str is not None:
            h, m_val = map(int, time_str.split(":"))
            t_min = h * 60 + m_val
            is_lunch = (12 * 60 <= t_min <= 14 * 60)
            is_dinner = (19 * 60 <= t_min <= 22 * 60)
            if not (is_lunch or is_dinner):
                return {
                    "role": "assistant",
                    "content": (
                        f"L'orario indicato (**{time_str}**) non rientra nei nostri orari di servizio.\n\n"
                        f"I turni di prenotazione sono:\n"
                        f"• **Pranzo**: dalle 12:00 alle 14:00 (ultimo arrivo 14:00)\n"
                        f"• **Cena**: dalle 19:00 alle 22:00 (ultimo arrivo 22:00)\n\n"
                        f"A che ora desidera prenotare?"
                    )
                }

        if time_str is None:
            return {
                "role": "assistant",
                "content": (
                    f"Ottimo, tavolo per **{party} persone** per **{_describe_date(target_d)}**!\n\n"
                    f"**A che ora** desidera venire?\n"
                    f"• **Pranzo**: dalle 12:00 alle 14:00\n"
                    f"• **Cena**: dalle 19:00 alle 22:00"
                )
            }

        # ----------------- PASSO 4: VERIFICA DISPONIBILITÀ SU DATABASE -----------------
        has_checked_this_slot = False
        for m in reversed(messages):
            if m.get("role") == "tool" and m.get("tool_name") == "check_availability":
                try:
                    c = json.loads(m.get("content", "{}"))
                    r = c.get("risultato", {})
                    if r.get("data") == target_d.isoformat() and r.get("ora") == time_str and r.get("persone") == party:
                        has_checked_this_slot = True
                        break
                except Exception:
                    pass

        has_created = any(m.get("role") == "tool" and m.get("tool_name") == "create_reservation" for m in messages)

        if not has_checked_this_slot and not has_created:
            return {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "function": {
                        "name": "check_availability",
                        "arguments": {
                            "date": target_d.isoformat(),
                            "time": time_str,
                            "party_size": party,
                        }
                    }
                }]
            }

        # ----------------- PASSO 5: NOME DEL CLIENTE -----------------
        if not name:
            return {
                "role": "assistant",
                "content": (
                    f"Tavolo disponibile per **{party} persone** per **{_describe_date(target_d)}** alle ore **{time_str}**!\n\n"
                    f"A quale **nome** desidera intestare la prenotazione?"
                )
            }

        # ----------------- PASSO 6: NUMERO DI TELEFONO -----------------
        if not phone:
            latest_digits = re.sub(r"\D", "", latest_user_text)
            if latest_digits and len(latest_digits) < 8:
                return {
                    "role": "assistant",
                    "content": (
                        f"Il recapito telefonico fornito (**{latest_user_text}**) non è valido.\n\n"
                        f"Per confermare la prenotazione a nome **{name}**, ci può indicare un **numero di telefono corretto** (almeno 8-10 cifre, cellulare o fisso)?"
                    )
                }
            return {
                "role": "assistant",
                "content": (
                    f"Perfetto, a nome **{name}**!\n\n"
                    f"Ci può indicare anche un **numero di telefono** di recapito per confermare la prenotazione?"
                )
            }

        # ----------------- PASSO 7: CREAZIONE E CONFERMA -----------------
        return {
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "function": {
                    "name": "create_reservation",
                    "arguments": {
                        "date": target_d.isoformat(),
                        "time": time_str,
                        "party_size": party,
                        "customer_name": name,
                        "contact": phone,
                    }
                }
            }]
        }

    # Se la domanda è fuori tema (cultura generale, scuola, ecc.) e non riguarda il ristorante
    off_topic_patterns = [
        r"\bchi ha scritto\b", r"\bdivina commedia\b", r"\bdante\b", r"\bcapitale\b",
        r"\bchi è\b", r"\bchi e'\b", r"\bchi era\b", r"\bchi sono\b", r"\bpoesia\b", r"\bpoeta\b",
        r"\bformula\b", r"\bequazione\b", r"\bteorema\b", r"\bcompiti\b", r"\bcalcola\b",
        r"\bchi ha vinto\b", r"\bprogramma in\b", r"\bcodice python\b", r"\bmeteo a\b"
    ]
    if any(re.search(p, latest_user_text, re.I) for p in off_topic_patterns):
        return {
            "role": "assistant",
            "content": "Mi scusi, ma come assistente virtuale del Ristorante Zio Pierino PSG posso esserle utile esclusivamente per quanto riguarda le attività del nostro locale: prenotazione tavoli, consultazione del menu marinaro e informazioni su orari o posizione a Porto San Giorgio. Come posso aiutarla per il nostro ristorante?"
        }

    # Risposta generica di benvenuto
    return {
        "role": "assistant",
        "content": "Buongiorno e benvenuto al Ristorante Zio Pierino PSG di Porto San Giorgio! Posso aiutarla a prenotare un tavolo, consultare il menu con prezzi e allergeni, o fornirle informazioni su orari e posizione. Come posso esserle utile?"
    }


TOOL_NAMES_SET = {
    "check_availability", "create_reservation", "get_reservation",
    "modify_reservation", "cancel_reservation", "get_menu", "get_restaurant_info"
}
TOOL_PATTERN = "|".join(TOOL_NAMES_SET)
_NAMED_TOOL_CALL = re.compile(rf"(?:^|\n|\s)(?:call:)?({TOOL_PATTERN})\s*\(?\s*(\{{.*?\}})\s*\)?", re.S)
_JSON_BLOCK_CALL = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.S)
_JSON_CALL = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.S)
_XML_CALL = re.compile(r"<function=([\w-]+)>(.*?)</function>", re.S)
_XML_PARAM = re.compile(r"<parameter=([\w-]+)>\s*(.*?)\s*</parameter>", re.S)
_LEFTOVERS = re.compile(r"</?tool_call>|<function=[^>]*>|</function>|<parameter=[^>]*>|</parameter>")


def normalize_message(message: dict) -> dict:
    """Ripulisce la risposta del modello.

    - rimuove il "ragionamento" tra tag <think>;
    - se il modello ha scritto una chiamata a strumento come testo (es. create_reservation {...} o ```json)
      invece di usare il canale nativo tool_calls, la recupera e la converte in un vero tool_call;
    - elimina tassativamente qualsiasi stringa di chiamata, sintassi di funzione o JSON
      dal corpo del testo, impedendo che l'utente o la voce sintetica leggano codice.
    """
    content = re.sub(r"<think>.*?</think>", "", message.get("content") or "", flags=re.S)
    calls = list(message.get("tool_calls") or [])

    # 1. Se non ci sono tool_calls strutturati da Ollama, cerchiamo le chiamate scritte come testo
    if not calls:
        # a) <tool_call> ... </tool_call>
        for m in _JSON_CALL.finditer(content):
            try:
                data = json.loads(m.group(1))
                name = data.get("name") or data.get("function")
                if name in TOOL_NAMES_SET:
                    calls.append({"function": {"name": name, "arguments": data.get("arguments", {})}})
            except (json.JSONDecodeError, KeyError, TypeError):
                pass

        # b) ```json {"name": "create_reservation", ...} ```
        for m in _JSON_BLOCK_CALL.finditer(content):
            try:
                data = json.loads(m.group(1))
                name = data.get("name")
                if name in TOOL_NAMES_SET:
                    calls.append({"function": {"name": name, "arguments": data.get("arguments", {})}})
            except (json.JSONDecodeError, KeyError, TypeError):
                pass

        # c) create_reservation {"customer_name": "Matteo", ...} o create_reservation({...})
        for m in _NAMED_TOOL_CALL.finditer(content):
            t_name = m.group(1)
            try:
                args = json.loads(m.group(2))
                calls.append({"function": {"name": t_name, "arguments": args.get("arguments", args)}})
            except (json.JSONDecodeError, KeyError, TypeError):
                pass

        # d) XML <function=create_reservation> ...
        for m in _XML_CALL.finditer(content):
            f_name = m.group(1)
            if f_name in TOOL_NAMES_SET:
                args = {k: v for k, v in _XML_PARAM.findall(m.group(2))}
                calls.append({"function": {"name": f_name, "arguments": args}})

        if calls:
            log.info("Recuperate %d chiamate a strumento scritte come testo dal modello", len(calls))
            message["tool_calls"] = calls

    # 2. PULIZIA TOTALE DI CONTENT: rimuove QUALSIASI residuo di tool call dal testo
    content = _JSON_CALL.sub("", content)
    content = _JSON_BLOCK_CALL.sub("", content)
    content = _NAMED_TOOL_CALL.sub("", content)
    content = _XML_CALL.sub("", content)
    content = _LEFTOVERS.sub("", content)
    content = re.sub(r'\{[^{}]*"(?:customer_name|party_size|date|time|contact|code)"[^{}]*\}', "", content)
    content = re.sub(rf'^(?:call:)?(?:{TOOL_PATTERN})\b.*$', '', content, flags=re.MULTILINE)
    content = re.sub(r'\n{3,}', '\n\n', content)

    message["content"] = content.strip()
    return message

