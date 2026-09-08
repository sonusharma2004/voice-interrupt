from __future__ import annotations

import io
import math
import struct
import wave


SAMPLE_RATE = 16_000
SAMPLE_WIDTH = 2


def pcm16_to_wav(pcm: bytes, sample_rate: int = SAMPLE_RATE) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(SAMPLE_WIDTH)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    return buf.getvalue()


def duration_ms(pcm: bytes, sample_rate: int = SAMPLE_RATE) -> float:
    if not pcm:
        return 0.0
    return (len(pcm) / SAMPLE_WIDTH) / sample_rate * 1000.0


def rms_pcm16(pcm: bytes) -> float:
    if len(pcm) < 2:
        return 0.0
    count = len(pcm) // 2
    total = 0.0
    for i in range(count):
        (sample,) = struct.unpack_from("<h", pcm, i * 2)
        total += sample * sample
    return math.sqrt(total / count) / 32768.0


def concat_pcm(*chunks: bytes) -> bytes:
    return b"".join(c for c in chunks if c)
