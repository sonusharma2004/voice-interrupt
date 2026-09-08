from __future__ import annotations

import logging
import re

from groq import AsyncGroq

from app.audio.dsp import pcm16_to_wav
from app.config import get_settings

log = logging.getLogger("harbor.stt")

# Whisper prompt is a fake prior transcript, not instructions.
WHISPER_HINT = (
    "Hey Cut. Book two seats for Hanuman Ansh at Phoenix, 7:10 PM. "
    "The 10:20 PM show. Two seats. Book a flight from Indore to Mumbai for two people, 6:35 AM. Stop."
)

_SEAT_SLIPS = (
    (r"\btuseets\b", "two seats"),
    (r"\btuseet\b", "two seats"),
    (r"\btoseets\b", "two seats"),
    (r"\btwoseats\b", "two seats"),
    (r"\btooseats\b", "two seats"),
    (r"\btu\s*seets\b", "two seats"),
    (r"\btwo\s*sits\b", "two seats"),
    (r"\btwo\s*sheets\b", "two seats"),
    (r"\btoo\s*seats\b", "two seats"),
    (r"\b2seats\b", "two seats"),
    (r"\btooseat\b", "two seats"),
    (r"\bthreeseats\b", "three seats"),
)


def repair_transcript(text: str) -> str:
    """Fix the slips Whisper makes on short booking follow-ups."""
    out = (text or "").strip()
    if not out:
        return ""
    out = re.sub(r"\b(\d{1,2})[-.](\d{2})\b", r"\1:\2", out)
    out = re.sub(r"\bcook\b(?=\s+(?:for|a|two|to|the|ticket|tickets|seats?))", "book", out, flags=re.I)
    # Whisper often hears Goa as "go": "Indore to go"
    out = re.sub(r"\bto\s+go\b(?!\s+to\b)", "to Goa", out, flags=re.I)
    out = re.sub(r"\bone\s+people\b", "one person", out, flags=re.I)
    for pat, repl in _SEAT_SLIPS:
        out = re.sub(pat, repl, out, flags=re.I)
    return re.sub(r"\s+", " ", out).strip()


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
        prompt=WHISPER_HINT,
    )
    raw = (getattr(resp, "text", None) or "").strip()
    text = repair_transcript(raw)
    if text != raw:
        log.info("stt: %s → %s", raw[:160], text[:160])
    else:
        log.info("stt: %s", text[:160])
    return text
