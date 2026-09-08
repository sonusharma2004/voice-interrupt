from __future__ import annotations

import logging

from groq import AsyncGroq

from app.audio.dsp import pcm16_to_wav
from app.config import get_settings

log = logging.getLogger("harbor.stt")


async def transcribe(pcm: bytes) -> str:
    settings = get_settings()
    if not settings.groq_api_key:
        raise RuntimeError("GROQ_API_KEY is missing")
    client = AsyncGroq(api_key=settings.groq_api_key)
    wav = pcm16_to_wav(pcm)
    resp = await client.audio.transcriptions.create(
        file=("utterance.wav", wav, "audio/wav"),
        model=settings.groq_stt_model,
        language="en",
        temperature=0.0,
        prompt="The assistant is named Cut. Hi Cut. Hey Cut. Hello Cut. Stop. Okay.",
    )
    text = (getattr(resp, "text", None) or "").strip()
    log.info("stt: %s", text[:160])
    return text
