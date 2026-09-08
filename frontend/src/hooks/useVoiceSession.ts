import { useCallback, useEffect, useRef, useState } from "react";
import { VoiceEngine } from "../audio/engine";
import { bytesToBase64 } from "../audio/resample";
import type { InspectorEvent, Line, Pipeline, SessionState } from "../types";

const ECHO_GUARD_MS = 400;
const BARGE_RMS = 0.055;
const PREROLL_FRAMES = 30;

function uid() {
  return Math.random().toString(36).slice(2, 10);
}

const emptyPipeline = (): Pipeline => ({
  generationId: "—",
  state: "idle",
  micLive: false,
  inSpeech: false,
  rms: 0,
  ttfaMs: null,
  lastCascade: [],
  events: [],
});

export function useVoiceSession() {
  const [state, setState] = useState<SessionState>("idle");
  const [lines, setLines] = useState<Line[]>([]);
  const [pipeline, setPipeline] = useState<Pipeline>(emptyPipeline);
  const [micOn, setMicOn] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [keysOk, setKeysOk] = useState<boolean | null>(null);
  const [socketOn, setSocketOn] = useState(false);

  const engineRef = useRef<VoiceEngine | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const stateRef = useRef<SessionState>("idle");
  const liveGenRef = useRef<string>("");
  const ignoreGenRef = useRef<Set<string>>(new Set());
  const speakingSinceRef = useRef<number>(0);
  const bargeWatchRef = useRef<number | null>(null);
  const assistantBufRef = useRef<string>("");
  const assistantIdRef = useRef<string | null>(null);
  const lastUiRef = useRef<number>(0);
  const lastRmsRef = useRef<number>(0);
  const openMicRef = useRef(true);
  const prerollRef = useRef<Uint8Array[]>([]);
  const handleRef = useRef<(msg: Record<string, unknown>) => void>(() => undefined);

  const pushEvent = useCallback((kind: string, detail: string) => {
    const ev: InspectorEvent = { id: uid(), at: Date.now(), kind, detail };
    setPipeline((p) => ({ ...p, events: [ev, ...p.events].slice(0, 10) }));
  }, []);

  const setSessionState = useCallback((next: SessionState) => {
    stateRef.current = next;
    if (next === "listening" || next === "interrupted") openMicRef.current = true;
    if (next === "transcribing" || next === "thinking" || next === "speaking") openMicRef.current = false;
    setState(next);
    setPipeline((p) => ({ ...p, state: next }));
  }, []);

  const strikeAssistant = useCallback(() => {
    const id = assistantIdRef.current;
    if (!id) return;
    setLines((prev) =>
      prev.map((l) => (l.id === id ? { ...l, interrupted: true, partial: false } : l))
    );
  }, []);

  const flushPlaybackNow = useCallback(() => {
    engineRef.current?.flush();
    pushEvent("playback", "flushed locally");
  }, [pushEvent]);

  const maybeBargeIn = useCallback(
    (reason: string) => {
      const current = stateRef.current;
      if (current !== "speaking" && current !== "thinking") return;
      if (current === "speaking") {
        const since = Date.now() - speakingSinceRef.current;
        if (since < ECHO_GUARD_MS) return;
        if (lastRmsRef.current < BARGE_RMS) return;
      }
      if (liveGenRef.current) ignoreGenRef.current.add(liveGenRef.current);
      openMicRef.current = true;
      flushPlaybackNow();
      strikeAssistant();
      const ws = wsRef.current;
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "barge_in", reason }));
        ws.send(JSON.stringify({ type: "speech_start" }));
        for (const frame of prerollRef.current) {
          ws.send(JSON.stringify({ type: "audio", data: bytesToBase64(frame) }));
        }
      }
      pushEvent("barge_in", reason);
    },
    [flushPlaybackNow, pushEvent, strikeAssistant]
  );

  const onSpeechStart = useCallback(() => {
    const current = stateRef.current;
    if (current === "listening" || current === "interrupted") {
      wsRef.current?.send(JSON.stringify({ type: "speech_start" }));
      return;
    }
    maybeBargeIn("user_cut_in");
  }, [maybeBargeIn]);

  const onSpeechEnd = useCallback(() => {
    if (stateRef.current === "listening" || stateRef.current === "interrupted") {
      wsRef.current?.send(JSON.stringify({ type: "speech_end" }));
    }
    if (bargeWatchRef.current) {
      window.clearTimeout(bargeWatchRef.current);
      bargeWatchRef.current = null;
    }
  }, []);

  const handleMessage = useCallback(
    (msg: Record<string, unknown>) => {
      const type = msg.type as string;
      const gen = (msg.generation_id as string) || "";
      if (gen && ignoreGenRef.current.has(gen) && type !== "cancelled") {
        return;
      }

      if (type === "state") {
        const next = msg.state as SessionState;
        if (gen) {
          liveGenRef.current = gen;
          setPipeline((p) => ({ ...p, generationId: gen }));
        }
        if (next === "speaking") speakingSinceRef.current = Date.now();
        if (next === "thinking") {
          assistantBufRef.current = "";
          assistantIdRef.current = uid();
          const id = assistantIdRef.current;
          setLines((prev) => [...prev, { id, role: "assistant", text: "", partial: true }]);
        }
        setSessionState(next);
        return;
      }

      if (type === "transcript_final") {
        const text = String(msg.text || "");
        setLines((prev) => [...prev, { id: uid(), role: "user", text }]);
        pushEvent("stt", text);
        return;
      }

      if (type === "llm_token") {
        const delta = String(msg.text || "");
        assistantBufRef.current += delta;
        const id = assistantIdRef.current;
        const text = assistantBufRef.current;
        if (id) {
          setLines((prev) => prev.map((l) => (l.id === id ? { ...l, text } : l)));
        }
        return;
      }

      if (type === "llm_done") {
        const id = assistantIdRef.current;
        if (id) {
          setLines((prev) => prev.map((l) => (l.id === id ? { ...l, partial: false } : l)));
        }
        return;
      }

      if (type === "tts_mp3") {
        if (gen && ignoreGenRef.current.has(gen)) return;
        if (!engineRef.current) engineRef.current = new VoiceEngine();
        if (!engineRef.current.onPlaybackDone) {
          engineRef.current.onPlaybackDone = () => {
            window.setTimeout(() => {
              wsRef.current?.send(JSON.stringify({ type: "playback_done" }));
            }, 350);
          };
        }
        const b64 = String(msg.data || "");
        const bin = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
        engineRef.current.enqueueMp3(bin.buffer);
        return;
      }

      if (type === "cancelled") {
        ignoreGenRef.current.add(gen);
        flushPlaybackNow();
        strikeAssistant();
        const cascade = (msg.cascade as Pipeline["lastCascade"]) || [];
        setPipeline((p) => ({ ...p, lastCascade: cascade }));
        pushEvent("cancel", String(msg.reason || "cancel"));
        if (msg.next_generation_id) {
          liveGenRef.current = String(msg.next_generation_id);
          setPipeline((p) => ({ ...p, generationId: String(msg.next_generation_id) }));
        }
        return;
      }

      if (type === "metrics") {
        setPipeline((p) => ({ ...p, ttfaMs: Number(msg.ttfa_ms) }));
        return;
      }

      if (type === "error") {
        setError(String(msg.message || "Server error"));
        pushEvent("error", String(msg.message));
      }
    },
    [flushPlaybackNow, pushEvent, setSessionState, strikeAssistant]
  );

  handleRef.current = handleMessage;

  const openSocket = useCallback(() => {
    const current = wsRef.current;
    if (current && (current.readyState === WebSocket.OPEN || current.readyState === WebSocket.CONNECTING)) {
      return;
    }
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws`);
    wsRef.current = ws;
    ws.onopen = () => {
      ws.send(JSON.stringify({ type: "session_start" }));
      setSocketOn(true);
      pushEvent("socket", "connected");
    };
    ws.onmessage = (ev) => {
      try {
        handleRef.current(JSON.parse(ev.data));
      } catch {
        /* ignore */
      }
    };
    ws.onerror = () => setError("Can't reach the server. Is FastAPI running on :8000?");
    ws.onclose = () => {
      setSocketOn(false);
      pushEvent("socket", "closed");
    };
  }, [pushEvent]);

  useEffect(() => {
    openSocket();
    void fetch("/api/health")
      .then((r) => r.json())
      .then((h) => setKeysOk(Boolean(h.ok)))
      .catch(() => setKeysOk(false));
    return () => {
      wsRef.current?.close();
      wsRef.current = null;
      void engineRef.current?.stop();
    };
  }, [openSocket]);

  const enableMic = useCallback(async () => {
    if (engineRef.current?.capture) {
      setMicOn(true);
      return;
    }
    setError(null);
    openSocket();
    const engine = engineRef.current ?? new VoiceEngine();
    engineRef.current = engine;
    engine.onPlaybackDone = () => {
      window.setTimeout(() => {
        wsRef.current?.send(JSON.stringify({ type: "playback_done" }));
      }, 350);
    };
    await engine.start({
      onFrame: (pcm, rms, speech) => {
        lastRmsRef.current = rms;
        const bytes = new Uint8Array(pcm);
        const copy = bytes.slice();
        const hold = prerollRef.current;
        hold.push(copy);
        if (hold.length > PREROLL_FRAMES) hold.shift();
        const now = performance.now();
        if (now - lastUiRef.current > 120) {
          lastUiRef.current = now;
          setPipeline((p) => ({ ...p, rms, inSpeech: speech, micLive: true }));
        }
        if (!openMicRef.current) return;
        wsRef.current?.send(JSON.stringify({ type: "audio", data: bytesToBase64(bytes) }));
      },
      onSpeechStart,
      onSpeechEnd,
    });
    setMicOn(true);
    setSessionState("listening");
  }, [onSpeechEnd, onSpeechStart, openSocket, setSessionState]);

  const disableMic = useCallback(async () => {
    await engineRef.current?.stop();
    engineRef.current = null;
    setMicOn(false);
    setPipeline((p) => ({ ...p, micLive: false, rms: 0 }));
  }, []);

  const sendText = useCallback(
    (raw: string) => {
      const text = raw.trim();
      if (!text) return;
      openSocket();
      const busy = stateRef.current === "speaking" || stateRef.current === "thinking";
      if (busy) {
        flushPlaybackNow();
        strikeAssistant();
      }
      setLines((prev) => [...prev, { id: uid(), role: "user", text }]);
      const payload = JSON.stringify({ type: "text", text });
      const ws = wsRef.current;
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(payload);
        return;
      }
      const timer = window.setInterval(() => {
        if (wsRef.current?.readyState === WebSocket.OPEN) {
          window.clearInterval(timer);
          wsRef.current.send(payload);
        }
      }, 40);
      window.setTimeout(() => window.clearInterval(timer), 3000);
    },
    [flushPlaybackNow, openSocket, strikeAssistant]
  );

  const newChat = useCallback(() => {
    flushPlaybackNow();
    setLines([]);
    setError(null);
    wsRef.current?.send(JSON.stringify({ type: "reset" }));
    setSessionState("listening");
  }, [flushPlaybackNow, setSessionState]);

  return {
    state,
    lines,
    pipeline,
    micOn,
    socketOn,
    error,
    keysOk,
    enableMic,
    disableMic,
    sendText,
    newChat,
  };
}
