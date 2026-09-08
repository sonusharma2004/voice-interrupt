import type { SessionState } from "../types";

const LABELS: Record<SessionState, string> = {
  idle: "Ready",
  listening: "Listening",
  transcribing: "Hearing you",
  thinking: "Thinking",
  speaking: "Speaking",
  interrupted: "Listening",
};

export function StatusDot({ state }: { state: SessionState }) {
  return (
    <span className={`status-pill is-${state}`}>
      <i />
      {LABELS[state]}
    </span>
  );
}
