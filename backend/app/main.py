from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings, keys_status
from app.rag.store import store
from app.session import VoiceSession

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("harbor")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = get_settings()
    if not settings.groq_api_key:
        log.warning("Missing GROQ_API_KEY in .env — STT and LLM will fail")
    await store.load()
    yield


app = FastAPI(title="Harbor & Rye", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health() -> dict:
    keys = keys_status()
    settings = get_settings()
    return {
        "ok": bool(keys.get("groq")),
        "keys": keys,
        "chunks": len(store.chunks),
        "llm": settings.groq_llm_model,
        "tts": settings.tts_provider,
    }


@app.websocket("/ws")
async def voice_socket(ws: WebSocket) -> None:
    await ws.accept()
    session = VoiceSession(ws)
    try:
        await session.run()
    except WebSocketDisconnect:
        log.info("client disconnected")
    except Exception:
        log.exception("session crashed")
        try:
            await ws.close()
        except Exception:
            pass
