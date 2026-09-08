import type { Desk } from "../types";

export function DeskCard({ desk }: { desk: Desk }) {
  const empty = desk.movies.length === 0 && desk.trips.length === 0;
  return (
    <div className="desk">
      <p className="desk-kicker">Demo holds</p>
      <p className="desk-sub">Not BookMyShow or MakeMyTrip — local catalog only.</p>
      {empty && <p className="desk-empty">Book a movie or a trip and it shows up here.</p>}
      {desk.movies.map((m) => (
        <article key={`${m.code}-${m.id}`} className="hold movie">
          <span className="hold-kind">Movie</span>
          <strong>{m.title}</strong>
          <p>
            {m.theater}
            <br />
            {m.date} · {m.time} · {m.screen} · {m.seats} seat{m.seats === 1 ? "" : "s"}
          </p>
          <p className="hold-meta">
            ₹{m.price} · {m.code}
          </p>
        </article>
      ))}
      {desk.trips.map((t) => (
        <article key={`${t.code}-${t.id}`} className="hold trip">
          <span className="hold-kind">{t.kind}</span>
          <strong>{t.title}</strong>
          <p>
            {t.detail}
            <br />
            {t.date} · {t.travelers} traveler{t.travelers === 1 ? "" : "s"}
          </p>
          <p className="hold-meta">
            ₹{t.price} · {t.code}
          </p>
        </article>
      ))}
    </div>
  );
}
