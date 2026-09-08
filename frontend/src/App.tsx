import { useEffect, useRef, useState } from "react";
import { Transcript } from "./components/Transcript";
import { Inspector } from "./components/Inspector";
import { DeskCard } from "./components/Ticket";
import { useVoiceSession } from "./hooks/useVoiceSession";

export function App() {
  const session = useVoiceSession();
  const [details, setDetails] = useState(false);
  const [draft, setDraft] = useState("");
  const area = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const el = area.current;
    if (!el) return;
    el.style.height = "24px";
    el.style.height = `${Math.min(Math.max(el.scrollHeight, 24), 160)}px`;
  }, [draft]);

  function submit() {
    const text = draft.trim();
    if (!text) return;
    session.sendText(text);
    setDraft("");
  }

  return (
    <div className="shell">
      <aside className="sidebar">
        <button type="button" className="new-chat" onClick={() => session.newChat()}>
          <span>+</span> New chat
        </button>
        <p className="side-note">Tap the mic. Say “stop” to hang up. Movies and trips are a local demo catalog, not the real sites.</p>
        <DeskCard desk={session.desk} />
      </aside>

      <div className="main">
        <header className="topbar">
          <div className="title-row">
            <button type="button" className="new-inline" onClick={() => session.newChat()}>
              New chat
            </button>
            <strong>Cut</strong>
          </div>
          <div className="top-actions">
            {session.micOn && <span className={`live-tag is-${session.state}`}>{label(session.state)}</span>}
            <button type="button" className="text-btn" onClick={() => setDetails(true)}>
              Details
            </button>
          </div>
        </header>

        <Transcript lines={session.lines} />
        {(session.desk.movies.length > 0 || session.desk.trips.length > 0) && (
          <div className="desk-mobile">
            <DeskCard desk={session.desk} />
          </div>
        )}

        <div className="dock">
          {session.error && <p className="err">{session.error}</p>}
          <div className="composer">
            <textarea
              ref={area}
              rows={1}
              value={draft}
              placeholder="Message Cut"
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  submit();
                }
              }}
            />
            <button
              type="button"
              className={`icon-btn mic ${session.micOn ? "on" : ""}`}
              title={session.micOn ? "Mute microphone" : "Start voice"}
              onClick={() => void (session.micOn ? session.disableMic() : session.enableMic())}
            >
              <MicIcon />
            </button>
            <button
              type="button"
              className="icon-btn send"
              title="Send"
              disabled={!draft.trim()}
              onClick={submit}
            >
              <SendIcon />
            </button>
          </div>
          <p className="disclaimer">
            {session.keysOk === false
              ? "API key missing — add GROQ_API_KEY to .env"
              : "Demo bookings only. Cut can make mistakes."}
          </p>
        </div>
      </div>

      <Inspector pipeline={session.pipeline} open={details} onClose={() => setDetails(false)} />
    </div>
  );
}

function label(state: string) {
  if (state === "speaking") return "Speaking";
  if (state === "thinking" || state === "transcribing") return "Working";
  if (state === "listening" || state === "interrupted") return "Listening";
  return "Ready";
}

function MicIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M12 14a3 3 0 0 0 3-3V7a3 3 0 1 0-6 0v4a3 3 0 0 0 3 3Z"
        stroke="currentColor"
        strokeWidth="1.8"
      />
      <path
        d="M5 11a7 7 0 0 0 14 0M12 18v3"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
      />
    </svg>
  );
}

function SendIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
      <path d="M3.4 20.6 21 12 3.4 3.4 3 10l11 2-11 2z" />
    </svg>
  );
}
