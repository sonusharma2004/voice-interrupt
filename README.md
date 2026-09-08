# Harbor & Rye

A café voice host that you can actually interrupt.

Browser microphone in, Mira speaks back, and if you cut her off mid-sentence playback dies immediately, the in-flight STT/LLM/TTS turn is cancelled, and your new words become the next turn. No leftover upstream request sitting there burning tokens.

## What is in here

- FastAPI WebSocket session with a generation id on every turn
- Client AudioWorklet capture + a flushable playback queue (20ms fade)
- Soft barge-in: backchannels do not cancel; ~260ms of real speech does
- Adaptive endpointing so trailing off (`and then I… um`) waits longer than a finished sentence
- Groq Whisper → OpenAI `gpt-4o-mini` (tools) → OpenAI `tts-1` streaming PCM
- A small café brain: menu RAG, tickets, table holds
- Pipeline inspector so the cancel cascade is visible on camera

## Run it

You need two terminals, Python 3.11+, and Node 20+.

```bash
# 1. keys
cp .env.example .env
# paste OPENAI_API_KEY and GROQ_API_KEY

# 2. backend
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# 3. frontend (other terminal)
cd frontend
npm install
npm run dev
```

Open [http://localhost:5173](http://localhost:5173). Click **Open the line**, allow the microphone, then talk.

## Demo script (~90 seconds)

1. “What’s vegan, and do you have oat milk?”
2. Cut her off: “Actually just a cortado and a croissant.”
3. Watch the inspector: playback flush, then TTS/LLM abort, struck-through text.
4. Trail off: “And also can I… wait…” — she should wait, then pick it up.
5. “Book a table for two tomorrow at ten. I’m Sam.”

## API keys

See the steps at the bottom of this file, or the note returned with the first run.

## Stack

| Piece | Choice |
|---|---|
| Backend | FastAPI + WebSockets + asyncio cancellation |
| Frontend | Vite, React, AudioWorklets |
| STT | Groq `whisper-large-v3-turbo` |
| LLM | OpenAI `gpt-4o-mini` + café tools |
| TTS | OpenAI `tts-1` PCM stream (24 kHz) |
| RAG | `text-embedding-3-small` over `/backend/app/knowledge` |
