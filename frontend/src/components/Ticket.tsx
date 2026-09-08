import type { Desk } from "../types";

function fillLabel(fill?: string) {
  if (fill === "fast_filling") return "Fast filling";
  if (fill === "almost_full") return "Almost full";
  if (fill === "sold_out") return "Sold out";
  if (fill === "coming_soon") return "Coming soon";
  return "Available";
}

function formatClock(raw?: string) {
  if (!raw) return "";
  const already = raw.match(/^(\d{1,2}):(\d{2})\s*(AM|PM)$/i);
  if (already) {
    return `${Number(already[1])}:${already[2]} ${already[3].toUpperCase()}`;
  }
  const m = raw.trim().match(/^(\d{1,2}):(\d{2})/);
  if (!m) return raw;
  let hour = Number(m[1]);
  const minute = m[2];
  const suffix = hour >= 12 ? "PM" : "AM";
  hour = hour % 12 || 12;
  return `${hour}:${minute} ${suffix}`;
}

function formatClocksInText(text: string) {
  return text.replace(/\b(\d{1,2}):(\d{2})\b/g, (value, hour, minute, offset) => {
    const after = text.slice(offset + value.length);
    if (/^\s*(AM|PM)/i.test(after)) return value;
    return formatClock(`${hour}:${minute}`);
  });
}

function niceDate(iso?: string) {
  if (!iso) return "";
  const d = new Date(`${iso.slice(0, 10)}T00:00:00`);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short", year: "numeric" });
}

export function DeskCard({ desk }: { desk: Desk }) {
  const empty = desk.movies.length === 0 && desk.trips.length === 0;
  return (
    <div className="desk">
      <p className="desk-kicker">Holds</p>
      <p className="desk-sub">Sandbox listings — not BookMyShow or MakeMyTrip.</p>
      {empty && <p className="desk-empty">Book a movie or a trip and it shows up here.</p>}
      {desk.movies.map((m) => (
        <article key={`${m.code}-${m.id}`} className="hold movie">
          <span className="hold-kind">{m.status === "coming_soon" ? "Upcoming" : "Movie"}</span>
          <strong>{m.title}</strong>
          <p>
            {m.theater}
            <br />
            {m.city ? `${m.city}` : ""}
            {m.city ? <br /> : null}
            {niceDate(m.date)} · {formatClock(m.time)}
            <br />
            {m.screen} · {m.seats} seat{m.seats === 1 ? "" : "s"}
          </p>
          <p className="hold-meta">
            {fillLabel(m.fill)} · ₹{m.price} · {m.code}
            {!m.confirmed ? " · reminder" : ""}
          </p>
        </article>
      ))}
      {desk.trips.map((t) => (
        <article key={`${t.code}-${t.id}`} className="hold trip">
          <span className="hold-kind">{t.kind}</span>
          <strong>{t.title}</strong>
          <p>
            {formatClocksInText(t.detail)}
            <br />
            {niceDate(t.date)}
            <br />
            {t.travelers} traveler{t.travelers === 1 ? "" : "s"}
          </p>
          <p className="hold-meta">
            ₹{t.price} · {t.code}
          </p>
        </article>
      ))}
    </div>
  );
}
