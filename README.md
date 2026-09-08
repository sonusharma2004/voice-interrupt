# Cut

A browser voice assistant you can actually interrupt — like ChatGPT out loud.

Talk or type about anything. If you cut it off mid-sentence, playback dies immediately, the in-flight STT/LLM/TTS turn is cancelled, and your new words become the next turn. No leftover upstream request sitting there burning tokens.

Say **stop** (or tap the mic) and voice mode hangs up: it goes quiet, generation is cancelled, and the microphone actually turns off. It does not answer “okay, I’m stopping” and keep listening.

## What is in here

- ChatGPT-style UI: sidebar, transcript, text box, mic, send
- Demo **box office** (BookMyShow-style) and **trip desk** (MakeMyTrip-style) with a local catalog, tools, and a ticket card
- FastAPI WebSocket session with a generation id on every turn
- Client AudioWorklet capture + a flushable playback queue
- Barge-in: talking over it flushes speakers and starts a new turn
- Hang-up: `stop`, `stop talking`, `goodbye`, `I’m going to go` mute the mic (Whisper often hears “stop” as “so” — that hangs up too)
- Mic is closed while it thinks/speaks so it does not transcribe itself
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

1. Tap the mic. “What’s on in Indore tonight?”
2. Talk over it: “Two for Hanuman Ansh at Phoenix, 7pm.” Watch fill and the ticket card.
3. “Any IMAX for Spider-Man at TI?”
4. “Book a morning flight from Indore to Goa.”
5. Say **stop**. Mic goes gray.

This catalog is **not** the real BookMyShow or MakeMyTrip sites. Cut cannot log in, take payment, or issue a live ticket. A judge can still see search → hold → confirmation code, and barge-in changing the booking.

## What we cannot do on a real site

BookMyShow and MakeMyTrip do not give a public booking API. A real checkout needs their partner access, your account, and payment. Scraping those sites to place an order is not part of this demo.

What we **can** ship for a live room: a sandbox that behaves like those products (showtimes, flights, hotels, confirmation codes) plus interrupt that actually cancels the turn.

## Stack

| Piece | Choice |
|---|---|
| Backend | FastAPI + WebSockets + asyncio cancellation |
| Frontend | Vite, React, AudioWorklets |
| STT | Groq `whisper-large-v3-turbo` |
| LLM | Groq `openai/gpt-oss-20b` + booking tools |
| TTS | Microsoft edge-tts (`en-US-AvaNeural`, mp3 per sentence) |

OpenAI TTS is still wired as an optional fallback if you set `TTS_PROVIDER=openai` and `OPENAI_API_KEY`.
