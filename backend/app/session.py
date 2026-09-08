from __future__ import annotations

import asyncio
import base64
import logging
import re
import time
import uuid
from typing import Any, Literal

from fastapi import WebSocket

from app.audio.dsp import duration_ms
from app.audio.endpointing import Endpointing
from app.providers import llm as llm_provider
from app.providers import stt as stt_provider
from app.providers import tts as tts_provider

log = logging.getLogger("harbor.session")

State = Literal[
    "idle",
    "listening",
    "transcribing",
    "thinking",
    "speaking",
    "interrupted",
]

_NOISE = re.compile(r"[^a-z0-9\s]+")


def _new_id() -> str:
    return uuid.uuid4().hex[:10]


def _norm(text: str) -> str:
    return _NOISE.sub("", text.lower()).strip()


def is_echo(text: str, last_assistant: str) -> bool:
    """Drop transcripts that are Cut hearing itself."""
    a = _norm(text)
    if not a:
        return True
    words = a.split()
    if len(words) < 2:
        return False
    b = _norm(last_assistant)
    if b and (a in b or b in a):
        return True
    aw, bw = set(words), set(b.split()) if b else set()
    if bw and len(aw & bw) / len(aw) >= 0.55:
        return True
    assistant_tics = (
        "let me know",
        "anything else",
        "would you like",
        "i'll check",
        "sounds great",
        "you're welcome",
        "take care",
        "have a great",
        "what else",
    )
    if any(p in a for p in assistant_tics) and (not b or len(aw & bw) >= 2):
        return True
    return False


STOP_PHRASES = {
    "stop",
    "stop it",
    "stop now",
    "stop talking",
    "stop listening",
    "stop speaking",
    "please stop",
    "please stop talking",
    "please stop listening",
    "thats enough",
    "that is enough",
    "never mind",
    "nevermind",
    "cancel",
    "quiet",
    "be quiet",
    "shut up",
    "hang up",
    "goodbye",
    "good bye",
    "bye",
    "bye bye",
    "were done",
    "we are done",
    "thats it",
    "enough",
    "end",
    "end voice",
    "mute",
    "you stop",
    "you stop now",
    "can you stop",
    "could you stop",
    "cut stop",
    "ok stop",
    "okay stop",
    "im going to go",
    "i am going to go",
    "im gonna go",
    "i am gonna go",
    "i gotta go",
    "i have to go",
    "i need to go",
    "gotta go",
    "got to go",
    "talk later",
    "see you",
    "see ya",
    "im done",
    "i am done",
}

LEAVE_SNIPPETS = (
    "going to go",
    "gonna go",
    "gotta go",
    "got to go",
    "have to go",
    "need to go",
    "gotta run",
)

# Whisper often clips "stop" to these during barge-in.
STOP_FRAGMENTS = {"so", "sto", "sop", "stahp", "stap", "stoped", "staap"}


def is_stop_command(text: str, *, after_interrupt: bool = False) -> bool:
    """Hang up voice for stop/goodbye. Also catch Whisper turning 'stop' into 'so'."""
    a = _norm(text)
    if not a:
        return False
    if a in STOP_PHRASES:
        return True
    words = a.split()
    if after_interrupt and a in STOP_FRAGMENTS:
        return True
    if any(w in {"stop", "stopped", "stopping"} for w in words):
        if words[0] in {"dont", "never", "cant", "cannot"}:
            return False
        if "sign" in words or (words == ["bus", "stop"] or words == ["stop", "sign"]):
            return False
        return len(words) <= 8
    if len(words) <= 6 and any(p in a for p in LEAVE_SNIPPETS):
        return True
    return False


class VoiceSession:
    def __init__(self, ws: WebSocket) -> None:
        self.ws = ws
        self.state: State = "idle"
        self.generation_id = _new_id()
        self.listen_buf = bytearray()
        self.preroll = bytearray()
        self.client_in_speech = False
        self.heard_user = False
        self.endpoint = Endpointing()
        self.cancel_event = asyncio.Event()
        self.playback_done = asyncio.Event()
        self.turn_task: asyncio.Task | None = None
        self.history: list[dict[str, Any]] = []
        self.interrupted_last = False
        self.last_speak_at = 0.0
        self.last_assistant = ""
        self._send_lock = asyncio.Lock()
        self._turn_lock = asyncio.Lock()
        self.turn_started_at = 0.0
        self.first_audio_at = 0.0
        self.deaf_until = 0.0

    async def send(self, payload: dict[str, Any]) -> None:
        async with self._send_lock:
            try:
                await self.ws.send_json(payload)
            except Exception:
                log.debug("send failed", exc_info=True)

    async def _set_state(self, state: State) -> None:
        self.state = state
        if state == "speaking":
            self.last_speak_at = time.monotonic()
        await self.send({"type": "state", "state": state, "generation_id": self.generation_id})

    def _wants_hang_up(self, text: str) -> bool:
        recently_spoke = self.last_speak_at and (time.monotonic() - self.last_speak_at) < 8.0
        return is_stop_command(
            text,
            after_interrupt=self.interrupted_last or bool(recently_spoke),
        )

    def _clear_listen(self) -> None:
        self.listen_buf.clear()
        self.preroll.clear()
        self.endpoint.reset()
        self.heard_user = False
        self.client_in_speech = False

    async def run(self) -> None:
        await self._set_state("listening")
        try:
            while True:
                message = await self.ws.receive()
                if message.get("type") == "websocket.disconnect":
                    break
                if message.get("bytes"):
                    await self.on_audio(message["bytes"])
                    continue
                text = message.get("text")
                if not text:
                    continue
                import json

                try:
                    msg = json.loads(text)
                except json.JSONDecodeError:
                    continue
                await self.on_message(msg)
        finally:
            await self.cancel("disconnect", announce=False)

    async def on_message(self, msg: dict[str, Any]) -> None:
        kind = msg.get("type")
        if kind == "audio":
            raw = base64.b64decode(msg.get("data", ""))
            await self.on_audio(raw)
        elif kind == "speech_start":
            self.client_in_speech = True
            if self.state in {"listening", "interrupted"}:
                self.heard_user = True
        elif kind == "speech_end":
            self.client_in_speech = False
        elif kind in {"barge_in", "cancel"}:
            await self.cancel(kind)
        elif kind == "playback_done":
            self.playback_done.set()
        elif kind == "text":
            spoken = str(msg.get("text") or "").strip()
            if spoken:
                await self.on_text(spoken)
        elif kind == "reset":
            await self.reset_chat()
        elif kind in {"hang_up", "voice_off"}:
            await self.hang_up_voice()
        elif kind in {"session_start", "voice_on"}:
            self._clear_listen()
            await self._set_state("listening")

    async def on_audio(self, pcm: bytes) -> None:
        if not pcm or time.monotonic() < self.deaf_until:
            return
        if self.state not in {"listening", "interrupted"}:
            return

        self.preroll.extend(pcm)
        max_preroll = int(16_000 * 2 * 0.35)
        if len(self.preroll) > max_preroll:
            self.preroll = bytearray(self.preroll[-max_preroll:])

        if not self.listen_buf and self.preroll:
            self.listen_buf.extend(self.preroll)
        else:
            self.listen_buf.extend(pcm)

        if self.endpoint.feed(pcm, self.client_in_speech) and self.heard_user:
            await self._finalize_utterance()

    async def _finalize_utterance(self) -> None:
        async with self._turn_lock:
            if self.state not in {"listening", "interrupted"}:
                return
            if self.turn_task and not self.turn_task.done():
                return
            pcm = bytes(self.listen_buf)
            self._clear_listen()
            if duration_ms(pcm) < 220:
                return
            self.generation_id = _new_id()
            self.cancel_event = asyncio.Event()
            self.playback_done = asyncio.Event()
            self.turn_started_at = time.perf_counter()
            self.first_audio_at = 0.0
            await self._set_state("transcribing")
            self.turn_task = asyncio.create_task(self._run_turn(pcm), name=f"turn-{self.generation_id}")

    async def _run_turn(self, pcm: bytes) -> None:
        gen = self.generation_id
        cancel = self.cancel_event
        try:
            text = await stt_provider.transcribe(pcm)
            if cancel.is_set() or gen != self.generation_id:
                return
            if not text or is_echo(text, self.last_assistant):
                log.info("drop transcript echo/empty: %s", text)
                await self._set_state("listening")
                return
            await self.send({"type": "transcript_final", "text": text, "generation_id": gen})
            if self._wants_hang_up(text):
                await self.hang_up_voice()
                return
            await self._generate(text, gen, cancel)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("turn failed")
            await self.send({"type": "error", "message": str(exc), "generation_id": gen})
            if self.state != "interrupted":
                self._clear_listen()
                await self._set_state("listening")

    async def on_text(self, text: str) -> None:
        if is_stop_command(text) or self._wants_hang_up(text):
            await self.hang_up_voice()
            return
        if self.state in {"transcribing", "thinking", "speaking"}:
            await self.cancel("typed")
        self.generation_id = _new_id()
        self.cancel_event = asyncio.Event()
        self.playback_done = asyncio.Event()
        self.turn_started_at = time.perf_counter()
        self.first_audio_at = 0.0
        self.turn_task = asyncio.create_task(
            self._generate(text, self.generation_id, self.cancel_event),
            name=f"text-{self.generation_id}",
        )

    async def reset_chat(self) -> None:
        if self.turn_task and not self.turn_task.done():
            await self.cancel("reset")
        self.history.clear()
        self.last_assistant = ""
        self.interrupted_last = False
        self._clear_listen()
        await self._set_state("listening")

    async def hang_up_voice(self) -> None:
        """GPT-style: stop talking and stop listening. No model reply."""
        self.cancel_event.set()
        self.playback_done.set()
        task = self.turn_task
        current = asyncio.current_task()
        if task and not task.done() and task is not current:
            task.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(self._await_cancelled(task)), timeout=0.5)
            except Exception:
                pass
        self._clear_listen()
        self.interrupted_last = False
        already_idle = self.state == "idle"
        if not already_idle:
            await self.send({"type": "voice_off", "reason": "stop_command"})
            await self._set_state("idle")
        log.info("voice hung up")

    async def _generate(self, text: str, gen: str, cancel: asyncio.Event) -> None:
        try:
            await self._set_state("thinking")
            spoken_parts: list[str] = []

            async def on_token(delta: str) -> None:
                await self.send({"type": "llm_token", "text": delta, "generation_id": gen})

            async for sentence in llm_provider.stream_spoken_reply(
                history=self.history,
                user_text=text,
                interrupted=self.interrupted_last,
                on_token=on_token,
                cancel=cancel,
            ):
                if cancel.is_set() or gen != self.generation_id:
                    return
                spoken_parts.append(sentence)
                if self.state != "speaking":
                    await self._set_state("speaking")
                await self._speak(sentence, gen, cancel)

            if cancel.is_set() or gen != self.generation_id:
                return

            full = " ".join(spoken_parts).strip()
            if full:
                self.history.append({"role": "user", "content": text})
                self.history.append({"role": "assistant", "content": full})
                self.last_assistant = full
            self.interrupted_last = False
            await self.send({"type": "llm_done", "generation_id": gen})
            if self.first_audio_at:
                await self.send(
                    {
                        "type": "metrics",
                        "generation_id": gen,
                        "ttfa_ms": round((self.first_audio_at - self.turn_started_at) * 1000),
                    }
                )
            if full:
                try:
                    await asyncio.wait_for(self.playback_done.wait(), timeout=20)
                except TimeoutError:
                    log.info("playback_done timeout")
            self.deaf_until = time.monotonic() + 0.55
            self._clear_listen()
            await self._set_state("listening")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("generate failed")
            await self.send({"type": "error", "message": str(exc), "generation_id": gen})
            if self.state != "interrupted":
                self._clear_listen()
                await self._set_state("listening")

    async def _speak(self, sentence: str, gen: str, cancel: asyncio.Event) -> None:
        clean = sentence.strip()
        if not clean:
            return
        try:
            mp3 = await tts_provider.synthesize_mp3(clean, cancel)
            if cancel.is_set() or gen != self.generation_id or not mp3:
                return
            if not self.first_audio_at:
                self.first_audio_at = time.perf_counter()
            await self.send(
                {
                    "type": "tts_mp3",
                    "data": base64.b64encode(mp3).decode("ascii"),
                    "generation_id": gen,
                }
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("tts failed")
            raise

    async def cancel(self, reason: str, announce: bool = True) -> None:
        if self.state in {"idle", "listening"} and reason == "disconnect":
            if self.turn_task and not self.turn_task.done():
                self.turn_task.cancel()
            return
        if self.state not in {"transcribing", "thinking", "speaking"} and reason != "disconnect":
            if not (self.turn_task and not self.turn_task.done()):
                return

        old_gen = self.generation_id
        t0 = time.perf_counter()
        cascade: list[dict[str, Any]] = []

        def mark(step: str) -> None:
            cascade.append({"step": step, "ms": round((time.perf_counter() - t0) * 1000, 1)})

        self.cancel_event.set()
        self.playback_done.set()
        mark("cancel_flag")

        task = self.turn_task
        if task and not task.done():
            task.cancel()
            mark("turn_task_cancel")
            try:
                await asyncio.wait_for(asyncio.shield(self._await_cancelled(task)), timeout=0.8)
            except Exception:
                pass
            mark("turn_task_dead")

        self.interrupted_last = True
        self.generation_id = _new_id()
        self.cancel_event = asyncio.Event()
        self.playback_done = asyncio.Event()
        # They are already talking — keep the mic hot and do not wait out an echo tail.
        self.deaf_until = 0.0
        self.listen_buf.clear()
        self.preroll.clear()
        self.endpoint.reset()
        self.heard_user = True
        self.client_in_speech = True
        if announce:
            await self.send(
                {
                    "type": "cancelled",
                    "reason": reason,
                    "generation_id": old_gen,
                    "next_generation_id": self.generation_id,
                    "cascade": cascade,
                }
            )
            await self._set_state("interrupted")
            await self._set_state("listening")
        log.info("cancelled %s gen=%s cascade=%s", reason, old_gen, cascade)

    @staticmethod
    async def _await_cancelled(task: asyncio.Task) -> None:
        try:
            await task
        except (asyncio.CancelledError, Exception):
            return
