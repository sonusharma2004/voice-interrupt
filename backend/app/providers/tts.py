from __future__ import annotations

import asyncio
import logging

import edge_tts

from app.config import get_settings

log = logging.getLogger("harbor.tts")

TTS_RATE = 24_000


async def synthesize_mp3(text: str, cancel: asyncio.Event) -> bytes:
    """Microsoft neural TTS (free, no key). One complete mp3 per sentence."""
    spoken = text.strip()
    if not spoken:
        return b""
    settings = get_settings()
    voice = settings.edge_tts_voice
    communicate = edge_tts.Communicate(spoken, voice, rate="+6%")
    parts: list[bytes] = []
    async for message in communicate.stream():
        if cancel.is_set():
            log.info("edge-tts aborted")
            return b""
        if message["type"] == "audio":
            parts.append(message["data"])
    return b"".join(parts)
