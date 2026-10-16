"""API HTTP del backend (FastAPI). Avvio: python -m app.main"""
from __future__ import annotations

import logging
import secrets
from contextlib import asynccontextmanager
from typing import Literal, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field

from . import config, db, services
from .agent import Agent
from .llm import LLMError, OllamaClient
from .privacy_guard import redact
from .services import BookingError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("backend")

llm = OllamaClient()
agent = Agent(llm)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    conn = db.connect()
    db.init_db(conn)
    conn.close()
    log.info("Database pronto: %s", config.DB_PATH)
    try:
        log.info("LLM locale: %s su %s", llm.resolve_model(), config.OLLAMA_URL)
    except LLMError as exc:
        log.error("%s - il BE parte comunque, /chat risponderà 503 finché l'LLM non è disponibile", exc)
    yield


app = FastAPI(title="Ristorante Zio Pierino PSG - Backend prenotazioni", version="1.0.0", lifespan=lifespan)


def require_api_key(x_api_key: str = Header(default="")) -> None:
    if config.API_KEY and not secrets.compare_digest(x_api_key, config.API_KEY):
        raise HTTPException(status_code=401, detail="API key mancante o errata")


def get_conn():
    conn = db.connect()
    try:
        yield conn
    finally:
        conn.close()


def booking_errors(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except BookingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


# ------------------------------------------------------------------ modelli

class ChatRequest(BaseModel):
    session_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    message: str = Field(min_length=1, max_length=2000)
    channel: Literal["chat", "voice"] = "chat"


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    actions: list[dict]
    privacy_warnings: list[str] = []


class ReservationIn(BaseModel):
    date: str
    time: str
    party_size: int
    customer_name: str
    contact: str = ""
    notes: str = ""


class ReservationPatch(BaseModel):
    date: Optional[str] = None
    time: Optional[str] = None
    party_size: Optional[int] = None
    notes: Optional[str] = None


# ------------------------------------------------------------------ endpoint

@app.get("/health")
def health():
    try:
        models = llm.available_models()
        llm_ok = any(m in models for m in (llm.model, f"{llm.model}:latest"))
    except LLMError:
        llm_ok = False
    return {"status": "ok", "llm_model": llm.model, "llm_ready": llm_ok}


@app.post("/api/v1/chat", response_model=ChatResponse, dependencies=[Depends(require_api_key)])
def chat(req: ChatRequest):
    message, found = redact(req.message)
    if found:
        log.warning("🔒 [PRIVACY GUARD] Dati personali in chiaro rilevati ed oscurati: %s", ", ".join(found))
    log.info("📥 [MESSAGGIO RICEVUTO da %s | sess: %s]: \"%s\"", req.channel.upper(), req.session_id[:8], message)
    try:
        result = agent.handle(req.session_id, message, req.channel)
    except LLMError as exc:
        log.error("❌ LLM non disponibile: %s", exc)
        raise HTTPException(status_code=503, detail="Assistente momentaneamente non disponibile") from None
    reply_preview = result.get("reply", "")
    if len(reply_preview) > 120:
        reply_preview = reply_preview[:120] + "..."
    log.info("📤 [RISPOSTA INVIATA AL CLIENT]: \"%s\"", reply_preview)
    return ChatResponse(**result, privacy_warnings=found)


@app.delete("/api/v1/chat/{session_id}", dependencies=[Depends(require_api_key)])
def reset_chat(session_id: str):
    log.info("🔄 [RESET SESSIONE CHAT]: %s", session_id)
    return {"reset": agent.sessions.reset(session_id)}


@app.get("/api/v1/info", dependencies=[Depends(require_api_key)])
def info(conn=Depends(get_conn)):
    log.info("ℹ️ [INFO RISTORANTE RICHIESTE]")
    return services.get_info(conn)


@app.get("/api/v1/menu", dependencies=[Depends(require_api_key)])
def menu(category: Optional[str] = None, diet: Optional[str] = None, conn=Depends(get_conn)):
    log.info("📋 [MENU RICHIESTO] cat=%s, dieta=%s", category, diet)
    return booking_errors(services.get_menu, conn, category, diet)


@app.get("/api/v1/availability", dependencies=[Depends(require_api_key)])
def availability(date: str, time: str, party_size: int = Query(ge=1), conn=Depends(get_conn)):
    log.info("🔎 [VERIFICA DISPONIBILITÀ] data=%s, ora=%s, persone=%d", date, time, party_size)
    return booking_errors(services.check_availability, conn, date, time, party_size)


@app.get("/api/v1/reservations", dependencies=[Depends(require_api_key)])
def list_reservations(date: Optional[str] = None, conn=Depends(get_conn)):
    log.info("📖 [LISTA PRENOTAZIONI] data=%s", date)
    return booking_errors(services.list_reservations, conn, date)


@app.post("/api/v1/reservations", status_code=201, dependencies=[Depends(require_api_key)])
def create(res: ReservationIn, conn=Depends(get_conn)):
    log.info("📝 [NUOVA PRENOTAZIONE RICEVUTA]: data=%s, ora=%s, persone=%d, cliente=%s",
             res.date, res.time, res.party_size, res.customer_name)
    for value in (res.customer_name, res.contact, res.notes):
        if redact(value)[1]:
            raise HTTPException(status_code=422, detail="Inviare solo dati pseudonimizzati, non dati personali in chiaro")
    return booking_errors(services.create_reservation, conn, res.date, res.time, res.party_size,
                          res.customer_name, res.contact, res.notes)


@app.get("/api/v1/reservations/{code}", dependencies=[Depends(require_api_key)])
def get_one(code: str, conn=Depends(get_conn)):
    log.info("🔍 [RICERCA PRENOTAZIONE #%s]", code)
    return booking_errors(services.get_reservation, conn, code)


@app.patch("/api/v1/reservations/{code}", dependencies=[Depends(require_api_key)])
def modify(code: str, patch: ReservationPatch, conn=Depends(get_conn)):
    log.info("✏️ [MODIFICA PRENOTAZIONE #%s] patch=%s", code, patch.dict(exclude_unset=True))
    return booking_errors(services.modify_reservation, conn, code, patch.date, patch.time,
                          patch.party_size, patch.notes)


@app.delete("/api/v1/reservations/{code}", dependencies=[Depends(require_api_key)])
def cancel(code: str, conn=Depends(get_conn)):
    log.info("❌ [CANCELLAZIONE PRENOTAZIONE #%s]", code)
    return booking_errors(services.cancel_reservation, conn, code)


def run():
    import uvicorn
    uvicorn.run(app, host=config.HOST, port=config.PORT)


if __name__ == "__main__":
    run()
