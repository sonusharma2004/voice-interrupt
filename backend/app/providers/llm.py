from __future__ import annotations

import logging
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from groq import AsyncGroq

from app.config import get_settings

log = logging.getLogger("harbor.llm")

SYSTEM = """You are Mira, a voice assistant in the browser — like talking to ChatGPT out loud.
Answer any topic: explanations, math, ideas, jokes, plans, follow-ups. You are not a café, shop, or booking bot.

How to speak:
- Plain spoken English. No markdown, bullets, URLs, emoji, or stage directions.
- A few tight sentences is enough unless they ask for more depth.
- Remember the conversation. If they change the subject, drop the old one.
- If they cut you off, answer ONLY the new request. Do not finish the previous thought.
"""

SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


async def stream_spoken_reply(
    history: list[dict[str, Any]],
    user_text: str,
    interrupted: bool,
    on_token: Callable[[str], Awaitable[None]],
    cancel: Any,
) -> AsyncIterator[str]:
    settings = get_settings()
    if not settings.groq_api_key:
        raise RuntimeError("GROQ_API_KEY is missing")

    client = AsyncGroq(api_key=settings.groq_api_key)
    messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM}]
    messages.extend(history[-20:])
    prefix = (
        "They interrupted you and changed the subject. Ignore your unfinished answer. Reply only to: "
        if interrupted
        else ""
    )
    messages.append({"role": "user", "content": prefix + user_text})

    if cancel.is_set():
        return

    stream = await client.chat.completions.create(
        model=settings.groq_llm_model,
        messages=messages,
        stream=True,
        temperature=0.7,
        max_tokens=450,
    )
    content = ""
    async for chunk in stream:
        if cancel.is_set():
            try:
                await stream.close()
            except Exception:
                pass
            return
        choice = chunk.choices[0] if chunk.choices else None
        if not choice or not choice.delta or not choice.delta.content:
            continue
        content += choice.delta.content
        await on_token(choice.delta.content)
        flushed, content = _flush_sentences(content)
        for sentence in flushed:
            yield sentence

    if content.strip() and not cancel.is_set():
        yield content.strip()


def _flush_sentences(buf: str) -> tuple[list[str], str]:
    if not SENTENCE_END.search(buf):
        return [], buf
    parts = SENTENCE_END.split(buf)
    *done, rest = parts
    return [p.strip() for p in done if p.strip()], rest
