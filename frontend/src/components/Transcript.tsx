import { useEffect, useRef } from "react";
import type { Line } from "../types";

export function Transcript({ lines }: { lines: Line[] }) {
  const scroller = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = scroller.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [lines]);

  if (lines.length === 0) {
    return (
      <div className="thread" ref={scroller}>
        <div className="empty">
          <div className="empty-logo">M</div>
          <h1>What can I help with?</h1>
        </div>
      </div>
    );
  }

  return (
    <div className="thread" ref={scroller}>
      <div className="thread-inner">
        {lines.map((line) =>
          line.role === "user" ? (
            <div key={line.id} className="row user">
              <div className="bubble">{line.text}</div>
            </div>
          ) : (
            <div key={line.id} className={`row assistant ${line.interrupted ? "cut" : ""} ${line.partial ? "partial" : ""}`}>
              <div className="avatar mira">M</div>
              <div className="prose">
                <p>{line.text || (line.partial ? "…" : "")}</p>
                {line.interrupted && <span className="stopped">Stopped</span>}
              </div>
            </div>
          )
        )}
      </div>
    </div>
  );
}
