from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from groq import AsyncGroq

from app.config import get_settings
from app.tools.desk import TOOL_SCHEMAS

log = logging.getLogger("harbor.llm")

SYSTEM = """You are Cut, a voice assistant in the browser — like talking to ChatGPT out loud.
Your name is Cut. If they say hi, hey, or hello Cut, greet them and offer to help.

You can also run a demo box office and travel desk:
- Movies: BookMyShow-style showtimes from the local catalog (Dune, Deadpool, Stree 2).
- Trips: MakeMyTrip-style flights, Goa hotels, and one weekend package.
This is NOT the real BookMyShow or MakeMyTrip websites. No login, no payment, no real ticket.
If they ask to pay or book on the real site, say the hold is a demo confirmation only.

For movies or trips: call the tools. Search first, then book. Read back title, place, time, people, price in rupees, and the CUT- code.
If they talk over you with a new time or movie, drop the old plan and book the new one.

You still answer any other topic. You are not a café.

How to speak:
- Plain spoken English. No markdown, bullets, URLs, emoji, or stage directions.
- A few tight sentences unless they ask for more.
- Remember the conversation.
"""

SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
BOOKISH = re.compile(
    r"\b(movie|film|ticket|show|pvr|inox|imax|dune|deadpool|stree|flight|fly|hotel|goa|"
    r"trip|bookmyshow|makemytrip|bengaluru|bangalore|mumbai|vistara|indigo)\b",
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
    if not settings.groq_api_key:
        raise RuntimeError("GROQ_API_KEY is missing")

    client = AsyncGroq(api_key=settings.groq_api_key)
    messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM}]
    messages.extend(history[-16:])
    prefix = (
        "They interrupted you. Ignore the unfinished answer. Reply only to: "
        if interrupted
        else ""
    )
    messages.append({"role": "user", "content": prefix + user_text})

    if cancel.is_set():
        return

    used_tools = False
    if execute_tool:
        used_tools = await _run_tools(client, settings.groq_llm_model, messages, execute_tool, cancel)

    if cancel.is_set():
        return

    if execute_tool and not used_tools and BOOKISH.search(user_text):
        hint = await execute_tool("search_docs", json.dumps({"query": user_text}))
        movies = await execute_tool("search_movies", json.dumps({"query": user_text}))
        trips = await execute_tool("search_trips", json.dumps({"query": user_text}))
        messages.append(
            {
                "role": "system",
                "content": (
                    "Use this demo catalog. Book with tools if they asked to book.\n"
                    f"docs: {hint}\nmovies: {movies}\ntrips: {trips}"
                ),
            }
        )
        await _run_tools(client, settings.groq_llm_model, messages, execute_tool, cancel)

    if cancel.is_set():
        return

    stream = await client.chat.completions.create(
        model=settings.groq_llm_model,
        messages=messages,
        stream=True,
        temperature=0.6,
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


async def _run_tools(
    client: AsyncGroq,
    model: str,
    messages: list[dict[str, Any]],
    execute_tool: Callable[[str, str], Awaitable[str]],
    cancel: Any,
) -> bool:
    used = False
    for _ in range(4):
        if cancel.is_set():
            return used
        try:
            resp = await client.chat.completions.create(
                model=model,
                messages=messages,
                tools=TOOL_SCHEMAS,
                tool_choice="auto",
                temperature=0.2,
                max_tokens=400,
            )
        except Exception:
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


def _flush_sentences(buf: str) -> tuple[list[str], str]:
    if not SENTENCE_END.search(buf):
        return [], buf
    parts = SENTENCE_END.split(buf)
    *done, rest = parts
    return [p.strip() for p in done if p.strip()], rest
