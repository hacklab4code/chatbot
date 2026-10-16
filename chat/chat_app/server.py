"""Server del chat-bot: interfaccia web + pseudonimizzazione + inoltro al BE.

Avvio: python -m chat_app.server  (poi aprire http://<ip-macchina-chat>:8001)
"""
import logging
from pathlib import Path

from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config
from .be_client import BackendClient, BackendError
from .privacy import Pseudonymizer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("chat")

STATIC = Path(__file__).parent / "static"

app = FastAPI(title="Zio Pierino PSG - Assistente prenotazioni", version="1.0.0")
app.mount("/static", StaticFiles(directory=STATIC), name="static")

backend = BackendClient(config.BE_URL, config.BE_API_KEY, config.BE_TIMEOUT)
pseudo = Pseudonymizer.from_dir(config.DATA_DIR, config.PSEUDO_SECRET)

SESSION_FIELD = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


class MessageIn(BaseModel):
    session_id: str = SESSION_FIELD
    message: str = Field(min_length=1, max_length=2000)
    channel: Literal["chat", "voice"] = "chat"


class ResetIn(BaseModel):
    session_id: str = SESSION_FIELD


@app.get("/")
def index():
    return FileResponse(
        STATIC / "index.html",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"}
    )


@app.get("/logo.jpg")
def logo():
    logo_path = STATIC / "logo.jpg"
    if logo_path.exists():
        return FileResponse(logo_path)
    raise HTTPException(status_code=404, detail="Logo not found")


@app.get("/hero.jpg")
def hero():
    hero_path = STATIC / "hero.jpg"
    if hero_path.exists():
        return FileResponse(hero_path)
    raise HTTPException(status_code=404, detail="Hero image not found")


@app.get("/api/status")
def status():
    try:
        return {"backend": "ok", **backend.health()}
    except BackendError as exc:
        return {"backend": "non raggiungibile", "detail": str(exc)}


@app.get("/api/info")
def get_info():
    try:
        return backend.info()
    except BackendError as exc:
        return {"error": str(exc)}


@app.get("/api/menu")
def get_menu(category: str = Query(default=None), diet: str = Query(default=None)):
    try:
        return backend.menu(category=category, diet=diet)
    except BackendError as exc:
        return {"error": str(exc)}


@app.get("/api/reservation/{code}")
def get_reservation(code: str):
    try:
        return backend.reservation(code.strip().upper())
    except BackendError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post("/api/message")
def message(body: MessageIn):
    masked, replaced = pseudo.pseudonymize(body.message.strip())
    if replaced:
        log.info("Pseudonimizzati %d dati personali: %s", len(replaced), [r["type"] for r in replaced])
    try:
        result = backend.chat(body.session_id, masked, channel=body.channel)
    except BackendError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    return {
        "reply": pseudo.reidentify(result["reply"]),
        "sent_to_backend": masked,  # mostrato nell'interfaccia per trasparenza
        "pseudonymized": [r["type"] for r in replaced],
    }


@app.post("/api/reset")
def reset(body: ResetIn):
    try:
        backend.reset(body.session_id)
    except BackendError:
        pass  # la sessione scadrà comunque sul BE
    return {"ok": True}


def run():
    import uvicorn
    uvicorn.run(app, host=config.CHAT_HOST, port=config.CHAT_PORT)


if __name__ == "__main__":
    run()
