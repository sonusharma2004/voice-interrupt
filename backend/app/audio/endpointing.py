from __future__ import annotations

import re
import time

from app.audio.dsp import duration_ms, rms_pcm16

# Wait for a real pause — ChatGPT-like, not twitchy.
COMPLETE_SILENCE_MS = 800
TRAIL_SILENCE_MS = 800
MIN_SPEECH_MS = 400
MAX_UTTERANCE_MS = 10_000
SPEECH_RMS = 0.025
# Keep this much audio before speech start so the first syllable survives.
PREROLL_MS = 350

INCOMPLETE = re.compile(
    r"(?i)(\b(and|or|but|so|if|when|because|um+|uh+|er+|like|wait|"
    r"also|then|the|a|an|i|i'd|i'm|i'll|can|could|would|just|maybe)\.?$)"
    r"|(\.\.\.$)|(-$)"
)


class Endpointing:
    """Hybrid energy clock + transcript completeness."""

    def __init__(self) -> None:
        self.speech_ms = 0.0
        self.silence_ms = 0.0
        self.heard_speech = False
        self.started_at: float | None = None
        self.prefer_trail = False

    def reset(self) -> None:
        self.speech_ms = 0.0
        self.silence_ms = 0.0
        self.heard_speech = False
        self.started_at = None
        self.prefer_trail = False

    def feed(self, pcm: bytes, client_in_speech: bool | None = None) -> bool:
        """Return True when the utterance should finalize."""
        now = time.monotonic()
        frame_ms = duration_ms(pcm)
        if frame_ms <= 0:
            return False

        energy_speech = rms_pcm16(pcm) >= SPEECH_RMS
        speaking = energy_speech if client_in_speech is None else (client_in_speech or energy_speech)

        if speaking:
            if not self.heard_speech:
                self.started_at = now
            self.heard_speech = True
            self.speech_ms += frame_ms
            self.silence_ms = 0.0
        elif self.heard_speech:
            self.silence_ms += frame_ms

        if not self.heard_speech or self.speech_ms < MIN_SPEECH_MS:
            return False

        elapsed = (now - (self.started_at or now)) * 1000.0
        if elapsed >= MAX_UTTERANCE_MS:
            return True

        need = TRAIL_SILENCE_MS if self.prefer_trail else COMPLETE_SILENCE_MS
        return self.silence_ms >= need

    def mark_incomplete(self, incomplete: bool) -> None:
        self.prefer_trail = incomplete
        if incomplete:
            self.silence_ms = 0.0

    def resume_after_partial(self) -> None:
        """Keep the turn open after a trail-off without requiring new speech."""
        self.prefer_trail = True
        self.heard_speech = True
        self.speech_ms = max(self.speech_ms, MIN_SPEECH_MS + 1)
        self.silence_ms = 0.0
        self.started_at = time.monotonic()


def looks_incomplete(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    if stripped[-1] in ".?!":
        return False
    return bool(INCOMPLETE.search(stripped))
