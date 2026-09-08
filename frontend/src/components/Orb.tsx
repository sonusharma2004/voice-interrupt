import type { SessionState } from "../types";

const LABELS: Record<SessionState, string> = {
  idle: "asleep",
  listening: "listening",
  transcribing: "hearing you",
  thinking: "thinking",
  speaking: "speaking",
  interrupted: "cut off",
};

export function Orb({ state, rms }: { state: SessionState; rms: number }) {
  const scale = 1 + Math.min(0.45, rms * 6);
  return (
    <div className={`orb-wrap is-${state}`}>
      <div className="orb-rings">
        <span />
        <span />
        <span />
      </div>
      <div className="orb" style={{ transform: `scale(${scale})` }}>
        <i />
      </div>
      <div className="orb-label">
        <em>Cut</em>
        <strong>{LABELS[state]}</strong>
      </div>
    </div>
  );
}
