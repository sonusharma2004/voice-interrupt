from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from groq import AsyncGroq
from openai import AsyncOpenAI

from app.config import get_settings
from app.tools.desk import TOOL_SCHEMAS

log = logging.getLogger("harbor.llm")

RATE_LIMIT_LINE = (
    "The model hit its daily limit. Movie and flight booking still work if you say book. "
    "Otherwise try again in a few minutes."
)

SYSTEM = """You are Cut, a voice assistant in the browser — like talking to ChatGPT out loud.
Your name is Cut. If they say hi, hey, or hello Cut, greet them and offer to help.

You can also run a demo box office and travel desk:
- Movies default to Indore: Phoenix Citadel, C21, Treasure Island (TI), Nexus Central, Velocity, Malhar.
- Now showing (Sep 2026): Hanuman Ansh, Toxic, Mirzapur: The Movie, Spider-Man: Brand New Day. Speak fill as available, fast filling, or almost full.
- Coming soon: Avengers: Doomsday on 18 Dec 2026 — reminder hold only, not a real ticket.
- Other cities: Mumbai, Delhi, Goa, Bengaluru.
- Trips: flights and hotels for Indore, Mumbai, Delhi, Goa, Bengaluru.
This is NOT the real BookMyShow or MakeMyTrip websites. No login, no payment, no real ticket.
If they ask to pay or book on the real site, say the hold is a demo confirmation only.

For movies or trips: call the tools. If they do not name a city, search Indore first. Search, offer choices, then book only after they pick a time and party size.
If they ask for a flight, hotel, or trip, do not list movies. If they ask for a movie, do not list flights.
If they talk over you with a new time or movie, drop the old plan and follow the new one.

You still answer any other topic. You are not a café.

How to speak:
- Write like ChatGPT. Natural sentences. No markdown, bullets, URLs, emoji, stage directions, or think tags.
- Never write <think> or a numbered analysis of the user's wording. Answer them directly.
- Times are always 12-hour, like 7:10 PM or 10:30 AM. Never say 19:10 or 18:50.
- Do not paste a ticket form or a field list. Do not copy ticket_text as stacked labels.
- Search first. Offer two or three options in prose, then ask which time and how many people or seats. Do not hold anything until they pick.
- After they pick, call the book tool, then confirm in a couple of sentences: what, where, 12-hour time, people, price, and the CUT- code.
- If a tool returns confirm_text, you may use that wording.
- Remember the conversation.
"""

SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
THINK_BLOCK = re.compile(r"<think>.*?</think>", re.I | re.S)
BOOKISH = re.compile(
    r"\b(movie|film|ticket|show|pvr|inox|imax|4dx|phoenix|c21|hanuman|ansh|toxic|mirzapur|"
    r"spider|spiderman|doomsday|flight|fly|hotel|goa|indore|mumbai|delhi|"
    r"trip|bookmyshow|makemytrip|bengaluru|bangalore|treasure)\b",
    re.I,
)


async def stream_spoken_reply(
    history: list[dict[str, Any]],
    user_text: str,
    interrupted: bool,
    on_token: Callable[[str], Awaitable[None]],
    cancel: Any,
    execute_tool: Callable[[str, str], Awaitable[str]] | None = None,
) -> AsyncIterator[str]:
    settings = get_settings()
    if not settings.groq_api_key and not settings.openai_api_key:
        raise RuntimeError("GROQ_API_KEY or OPENAI_API_KEY is missing")

    messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM}]
    messages.extend(history[-8:])
    if interrupted:
        messages.append(
            {
                "role": "system",
                "content": "The user talked over you. Drop the unfinished reply and answer only their new words.",
            }
        )
    messages.append({"role": "user", "content": user_text})

    if cancel.is_set():
        return

    try:
        used_tools = False
        if execute_tool:
            used_tools = await _run_tools(messages, execute_tool, cancel)

        if cancel.is_set():
            return

        if execute_tool and not used_tools and BOOKISH.search(user_text):
            movies = await execute_tool("search_movies", json.dumps({"query": user_text}))
            trips = await execute_tool("search_trips", json.dumps({"query": user_text}))
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "Use this demo catalog. Book with tools if they asked to book.\n"
                        f"movies: {movies[:1800]}\ntrips: {trips[:1200]}"
                    ),
                }
            )
            await _run_tools(messages, execute_tool, cancel)

        if cancel.is_set():
            return

        stream = await _create(
            messages=messages,
            stream=True,
            temperature=0.6,
            max_tokens=280,
        )
    except Exception as exc:
        if is_rate_limit(exc) or is_model_missing(exc):
            log.warning("llm unavailable: %s", exc)
            await on_token(RATE_LIMIT_LINE)
            yield RATE_LIMIT_LINE
            return
        raise

    raw = ""
    spoken = ""
    sent = 0
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
        raw += choice.delta.content
        visible = _visible_speech(raw)
        if len(visible) <= sent:
            continue
        delta = visible[sent:]
        sent = len(visible)
        await on_token(delta)
        spoken += delta
        flushed, spoken = _flush_sentences(spoken)
        for sentence in flushed:
            yield sentence

    leftover = _visible_speech(spoken).strip()
    if leftover and not cancel.is_set():
        yield leftover


async def _create(**kwargs: Any) -> Any:
    settings = get_settings()
    groq_models: list[str] = []
    for model in (settings.groq_llm_model, settings.groq_llm_fallback):
        if model and model not in groq_models:
            groq_models.append(model)
    last: Exception | None = None
    if settings.groq_api_key:
        client = AsyncGroq(api_key=settings.groq_api_key, max_retries=0)
        for i, model in enumerate(groq_models):
            try:
                log.info("llm groq %s", model)
                groq_kwargs = dict(kwargs)
                if "qwen" in model.lower():
                    groq_kwargs["reasoning_format"] = "hidden"
                    extra = dict(groq_kwargs.get("extra_body") or {})
                    extra["reasoning_effort"] = "none"
                    groq_kwargs["extra_body"] = extra
                return await client.chat.completions.create(model=model, **groq_kwargs)
            except Exception as exc:
                last = exc
                nxt = groq_models[i + 1] if i + 1 < len(groq_models) else "openai"
                if is_rate_limit(exc):
                    log.warning("%s on %s, skipping Groq retries, trying %s", type(exc).__name__, model, nxt)
                    break
                if is_model_missing(exc):
                    log.warning("%s on %s, trying %s", type(exc).__name__, model, nxt)
                    continue
                raise
    if settings.openai_api_key:
        oai = AsyncOpenAI(api_key=settings.openai_api_key)
        try:
            log.info("llm openai %s", settings.openai_llm_model)
            return await oai.chat.completions.create(model=settings.openai_llm_model, **kwargs)
        except Exception as exc:
            last = exc
            raise
    assert last is not None
    raise last


def is_model_missing(exc: BaseException) -> bool:
    if getattr(exc, "status_code", None) == 404:
        return True
    text = f"{type(exc).__name__} {exc}".lower()
    return "not_found" in text or "does not exist" in text


def is_rate_limit(exc: BaseException) -> bool:
    if getattr(exc, "status_code", None) == 429:
        return True
    text = f"{type(exc).__name__} {exc}".lower()
    return "rate_limit" in text or "429" in text


async def _run_tools(
    messages: list[dict[str, Any]],
    execute_tool: Callable[[str, str], Awaitable[str]],
    cancel: Any,
) -> bool:
    used = False
    for _ in range(4):
        if cancel.is_set():
            return used
        try:
            resp = await _create(
                messages=messages,
                tools=TOOL_SCHEMAS,
                tool_choice="auto",
                temperature=0.2,
                max_tokens=280,
            )
        except Exception as exc:
            if is_rate_limit(exc) or is_model_missing(exc):
                raise
            log.exception("tool round failed")
            return used
        choice = resp.choices[0] if resp.choices else None
        msg = choice.message if choice else None
        if not msg or not getattr(msg, "tool_calls", None):
            return used
        used = True
        dump = msg.model_dump(exclude_none=True)
        messages.append(dump)
        for call in msg.tool_calls:
            if cancel.is_set():
                return used
            name = call.function.name
            args = call.function.arguments or "{}"
            log.info("tool %s %s", name, args[:180])
            result = await execute_tool(name, args)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": result,
                }
            )
    return used


def _visible_speech(text: str) -> str:
    """Drop Qwen chain-of-thought so it never hits the transcript or TTS."""
    out = THINK_BLOCK.sub(" ", text or "")
    out = re.sub(r"<think>.*", " ", out, flags=re.I | re.S)
    return re.sub(r"[ \t]+\n", "\n", out).lstrip()


def _flush_sentences(buf: str) -> tuple[list[str], str]:
    if not SENTENCE_END.search(buf):
        return [], buf
    parts = SENTENCE_END.split(buf)
    *done, rest = parts
    return [p.strip() for p in done if p.strip()], rest
