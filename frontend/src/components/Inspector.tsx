import type { Pipeline } from "../types";

export function Inspector({
  pipeline,
  open,
  onClose,
}: {
  pipeline: Pipeline;
  open: boolean;
  onClose: () => void;
}) {
  if (!open) return null;

  const lanes = [
    { id: "mic", on: pipeline.micLive, note: pipeline.inSpeech ? "speech" : "idle" },
    { id: "stt", on: pipeline.state === "transcribing", note: pipeline.state === "transcribing" ? "on" : "—" },
    { id: "llm", on: pipeline.state === "thinking", note: pipeline.state === "thinking" ? "on" : "—" },
    { id: "tts", on: pipeline.state === "speaking", note: pipeline.state === "speaking" ? "on" : "—" },
  ];

  return (
    <div className="drawer-back" onClick={onClose} role="presentation">
      <aside className="drawer" onClick={(e) => e.stopPropagation()}>
        <header>
          <strong>Pipeline</strong>
          <button type="button" onClick={onClose}>
            Close
          </button>
        </header>
        <p className="gen">Turn {pipeline.generationId}</p>
        <div className="lanes">
          {lanes.map((lane) => (
            <div key={lane.id} className={`lane ${lane.on ? "on" : ""}`}>
              <b>{lane.id}</b>
              <small>{lane.note}</small>
            </div>
          ))}
        </div>
        <div className="meter">
          <span>Mic</span>
          <div>
            <i style={{ width: `${Math.min(100, pipeline.rms * 420)}%` }} />
          </div>
        </div>
        <p className="meta">
          {pipeline.ttfaMs != null ? `First audio ${pipeline.ttfaMs} ms` : "Waiting for a turn"}
        </p>
        {pipeline.lastCascade.length > 0 && (
          <ul className="cascade">
            {pipeline.lastCascade.map((step) => (
              <li key={step.step}>
                {step.step}
                <span>{step.ms} ms</span>
              </li>
            ))}
          </ul>
        )}
      </aside>
    </div>
  );
}
