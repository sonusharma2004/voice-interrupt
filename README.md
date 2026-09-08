# Mira

A browser voice assistant you can actually interrupt — like ChatGPT out loud.

Talk or type about anything. If you cut Mira off mid-sentence, playback dies immediately, the in-flight STT/LLM/TTS turn is cancelled, and your new words become the next turn. No leftover upstream request sitting there burning tokens.

Say **stop** (or tap the mic) and voice mode hangs up: she goes quiet, generation is cancelled, and the microphone actually turns off. She does not answer “okay, I’m stopping” and keep listening.

## What is in here

- ChatGPT-style UI: sidebar, transcript, text box, mic, send
- FastAPI WebSocket session with a generation id on every turn
- Client AudioWorklet capture + a flushable playback queue
- Barge-in: talking over her flushes speakers and starts a new turn
- Hang-up: `stop`, `stop talking`, `goodbye`, `I’m going to go` mute the mic (Whisper often hears “stop” as “so” — that hangs up too)
- Mic is closed while she thinks/speaks so she does not transcribe herself
- Adaptive endpointing so trailing off (`and then I… um`) waits longer than a finished sentence
- Pipeline inspector (Details) so the cancel cascade is visible on camera

## Run it

You need two terminals, Python 3.11+, and Node 20+. Groq is enough; OpenAI is optional.

```bash
# 1. keys
cp .env.example .env
# paste GROQ_API_KEY

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

Open [http://localhost:5173](http://localhost:5173). Tap the **mic**, allow the microphone, then talk. You can also type and press Enter.

## Demo script (~90 seconds)

1. Tap the mic. “Explain gravity like I’m five.”
2. Cut her off: “Actually, what’s 17 times 24?”
3. Watch Details: playback flush, then TTS/LLM abort, struck-through text.
4. Trail off: “And also can you… wait…” — she should wait, then pick it up.
5. Say **stop**. Speech dies, the mic button goes gray, she does not keep chatting. Tap the mic to talk again.

## Stack

| Piece | Choice |
|---|---|
| Backend | FastAPI + WebSockets + asyncio cancellation |
| Frontend | Vite, React, AudioWorklets |
| STT | Groq `whisper-large-v3-turbo` |
| LLM | Groq `openai/gpt-oss-20b` (no tools; general chat) |
| TTS | Microsoft edge-tts (`en-US-AvaNeural`, mp3 per sentence) |

OpenAI TTS is still wired as an optional fallback if you set `TTS_PROVIDER=openai` and `OPENAI_API_KEY`.
