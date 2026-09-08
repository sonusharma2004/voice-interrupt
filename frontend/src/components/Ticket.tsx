import type { Ticket } from "../types";

export function TicketCard({ ticket }: { ticket: Ticket }) {
  return (
    <aside className="ticket">
      <div className="ticket-head">
        <span>Harbor & Rye</span>
        <small>418 Willow · guest ticket</small>
      </div>
      <ul>
        {ticket.lines.length === 0 && <li className="ghost">No items yet</li>}
        {ticket.lines.map((line, i) => (
          <li key={`${line.item}-${i}`}>
            <b>
              {line.qty}× {line.item}
            </b>
            {line.mods && <small>{line.mods}</small>}
          </li>
        ))}
      </ul>
      <div className={`seal ${ticket.confirmed ? "on" : ""}`}>
        {ticket.confirmed ? "sent to the bar" : "open ticket"}
      </div>
      {ticket.bookings.length > 0 && (
        <div className="holds">
          <span>Table holds</span>
          {ticket.bookings.map((b, i) => (
            <p key={i}>
              {b.party} · {b.date} {b.time}
              <br />
              <em>{b.name}</em>
            </p>
          ))}
        </div>
      )}
    </aside>
  );
}
