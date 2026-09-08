from __future__ import annotations

import copy
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable

from app.rag.store import store
from app.tools.catalog import build_shows, build_trips

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "search_docs",
            "description": "Search movie listings, trip inventory, and demo booking rules.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_movies",
            "description": "List live-looking movie shows. Defaults to Indore. Filter by title, city, or cinema (Phoenix, C21, TI / Treasure Island).",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "city": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "book_movie",
            "description": "Hold movie tickets in the demo box office. Use a show_id from search_movies when you have one.",
            "parameters": {
                "type": "object",
                "properties": {
                    "show_id": {"type": "string"},
                    "title": {"type": "string"},
                    "theater": {"type": "string"},
                    "time": {"type": "string"},
                    "city": {"type": "string"},
                    "seats": {"type": "integer"},
                    "name": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_trips",
            "description": "List demo flights, hotels, and packages (MakeMyTrip-style). Cities include Indore, Mumbai, Delhi, Goa, Bengaluru.",
            "parameters": {
                "type": "object",
                "properties": {
                    "origin": {"type": "string"},
                    "destination": {"type": "string"},
                    "kind": {
                        "type": "string",
                        "description": "flight, hotel, or package",
                    },
                    "query": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "book_trip",
            "description": "Hold a demo flight, hotel, or weekend package. Prefer trip_id from search_trips.",
            "parameters": {
                "type": "object",
                "properties": {
                    "trip_id": {"type": "string"},
                    "travelers": {"type": "integer"},
                    "name": {"type": "string"},
                    "date": {"type": "string"},
                },
                "required": ["trip_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_bookings",
            "description": "Read back movie tickets and trip holds for this session.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


@dataclass
class MovieHold:
    id: str
    title: str
    theater: str
    city: str
    time: str
    date: str
    seats: int
    screen: str
    price: int
    code: str
    fill: str = "available"
    status: str = "now_showing"
    confirmed: bool = True


@dataclass
class TripHold:
    id: str
    kind: str
    title: str
    detail: str
    date: str
    travelers: int
    price: int
    code: str
    confirmed: bool = True


@dataclass
class DeskState:
    movies: list[MovieHold] = field(default_factory=list)
    trips: list[TripHold] = field(default_factory=list)

    def snapshot(self) -> dict[str, Any]:
        return {
            "movies": [asdict(x) for x in self.movies],
            "trips": [asdict(x) for x in self.trips],
        }


def _city_from_text(text: str) -> str:
    a = text.lower()
    if any(w in a for w in ("indore", "idr")):
        return "Indore"
    if any(w in a for w in ("mumbai", "bombay")):
        return "Mumbai"
    if any(w in a for w in ("delhi", "ncr", "saket")):
        return "Delhi"
    if any(w in a for w in ("goa", "panaji", "margao")):
        return "Goa"
    if any(w in a for w in ("bengaluru", "bangalore", "blr")):
        return "Bengaluru"
    return ""


def _parse_date(raw: str | None) -> str:
    today = datetime.now().date()
    if not raw:
        return today.isoformat()
    value = raw.strip().lower()
    if value in {"today", ""}:
        return today.isoformat()
    if value in {"tomorrow"}:
        return (today + timedelta(days=1)).isoformat()
    return raw.strip()


def _norm_time(raw: str) -> str | None:
    text = raw.strip().lower().replace(" ", "").replace(".", "")
    if not text:
        return None
    meridiem = ""
    if text.endswith("am") or text.endswith("pm"):
        meridiem = text[-2:]
        text = text[:-2]
    if ":" in text:
        hh, mm = text.split(":", 1)
    else:
        hh, mm = text, "00"
    try:
        hour = int(re.sub(r"\D", "", hh) or "0")
        minute = int(re.sub(r"\D", "", mm)[:2] or "0")
    except ValueError:
        return None
    if meridiem == "pm" and hour < 12:
        hour += 12
    if meridiem == "am" and hour == 12:
        hour = 0
    return f"{hour:02d}:{minute:02d}"


def format_clock(raw: str | None) -> str:
    """24-hour '19:10' or '7:10pm' → '7:10 PM'."""
    if not raw:
        return ""
    text = str(raw).strip()
    if re.search(r"(?i)\b(am|pm)\b", text):
        parsed = _norm_time(text)
        if not parsed:
            return re.sub(r"\s+", " ", text.upper().replace(".", ""))
        text = parsed
    match = re.match(r"^(\d{1,2}):(\d{2})", text)
    if not match:
        parsed = _norm_time(text)
        if not parsed:
            return str(raw).strip()
        match = re.match(r"^(\d{1,2}):(\d{2})", parsed)
        if not match:
            return str(raw).strip()
    hour = int(match.group(1))
    minute = int(match.group(2))
    suffix = "AM" if hour < 12 else "PM"
    hour12 = hour % 12 or 12
    return f"{hour12}:{minute:02d} {suffix}"


def format_clocks_in_text(text: str) -> str:
    return re.sub(r"\b(\d{1,2}):(\d{2})\b", lambda m: format_clock(m.group(0)), text or "")


def _fill_label(fill: str | None) -> str:
    return {
        "fast_filling": "fast filling",
        "almost_full": "almost full",
        "sold_out": "sold out",
        "available": "seats open",
        "coming_soon": "coming soon",
    }.get(fill or "", (fill or "").replace("_", " "))


def _nice_date(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        day = datetime.strptime(str(iso)[:10], "%Y-%m-%d")
        return f"{day.strftime('%a')} {day.day} {day.strftime('%b %Y')}"
    except ValueError:
        return str(iso)


def _card(header: str, fields: list[str], extra: str = "") -> str:
    lines = [header, ""]
    lines.extend(field for field in fields if field)
    body = "\n".join(lines).rstrip()
    extra = extra.strip()
    if extra:
        body = f"{body}\n\n{extra}"
    return body


def format_movie_ticket(ticket: dict[str, Any], extra: str = "", waitlist: bool = False) -> str:
    header = "Reminder hold — advance booking is not live yet." if waitlist else "Here's your ticket."
    seats = int(ticket.get("seats") or 0)
    seat_word = "seat" if seats == 1 else "seats"
    theater = str(ticket.get("theater") or "")
    city = str(ticket.get("city") or "")
    if city and city.lower() in theater.lower():
        city = ""
    return _card(
        header,
        [
            str(ticket.get("title") or ""),
            theater,
            city,
            ", ".join(p for p in (_nice_date(ticket.get("date")), format_clock(ticket.get("time"))) if p),
            " · ".join(p for p in (str(ticket.get("screen") or ""), f"{seats} {seat_word}") if p),
            f"{ticket.get('price', 0)} rupees",
            _fill_label(ticket.get("fill")),
            f"Code {ticket.get('code')}" if ticket.get("code") else "",
        ],
        extra=extra,
    )


def format_trip_ticket(booking: dict[str, Any]) -> str:
    travelers = int(booking.get("travelers") or 1)
    people = "traveler" if travelers == 1 else "travelers"
    return _card(
        "Here's your trip.",
        [
            str(booking.get("title") or ""),
            format_clocks_in_text(str(booking.get("detail") or "")),
            _nice_date(booking.get("date")),
            f"{travelers} {people}",
            f"{booking.get('price', 0)} rupees",
            f"Code {booking.get('code')}" if booking.get("code") else "",
        ],
    )


def _hay(item: dict[str, Any]) -> str:
    return " ".join(
        str(item.get(k, ""))
        for k in (
            "id",
            "title",
            "theater",
            "city",
            "screen",
            "kind",
            "detail",
            "origin",
            "destination",
            "search",
            "language",
            "status",
        )
    ).lower()


ALIASES = {
    "bangalore": "bengaluru",
    "blr": "bengaluru",
    "bom": "mumbai",
    "bombay": "mumbai",
    "del": "delhi",
    "spiderman": "spider",
    "dooms": "doomsday",
    "ansh": "hanuman",
    "ti": "treasure",
    "c21": "c21",
}


def _match(item: dict[str, Any], query: str) -> bool:
    if not query.strip():
        return True
    blob = _hay(item)
    terms = [t for t in re.findall(r"[a-z0-9]+", query.lower()) if len(t) > 1]
    skip = {"the", "movie", "show", "ticket", "tickets", "please", "today", "tonight"}
    mapped = [ALIASES.get(t, t) for t in terms if t not in skip]
    if not mapped:
        return True
    return all(t in blob for t in mapped)


def _time_close(show_time: str, wanted: str | None) -> bool:
    if not wanted:
        return True
    if show_time == wanted:
        return True
    try:
        sh, sm = map(int, show_time.split(":"))
        wh, wm = map(int, wanted.split(":"))
        return abs((sh * 60 + sm) - (wh * 60 + wm)) <= 25
    except ValueError:
        return False


def _public_show(s: dict[str, Any]) -> dict[str, Any]:
    keep = (
        "id",
        "title",
        "theater",
        "city",
        "time",
        "screen",
        "language",
        "rating",
        "price",
        "seats",
        "fill",
        "status",
        "opens",
        "as_of",
    )
    row = {k: s[k] for k in keep if k in s}
    if s.get("time"):
        row["time_12"] = format_clock(s["time"])
    return row


def _public_trip(t: dict[str, Any]) -> dict[str, Any]:
    row = dict(t)
    if t.get("time"):
        row["time_12"] = format_clock(t["time"])
    row["detail"] = format_clocks_in_text(str(t.get("detail") or ""))
    return row


class DeskTools:
    def __init__(self, on_change: Callable[[dict], Awaitable[None]] | None = None) -> None:
        self.state = DeskState()
        self.on_change = on_change
        self.shows = copy.deepcopy(build_shows())
        self.trips = copy.deepcopy(build_trips())
        self._n = 0

    def reset(self) -> None:
        self.state = DeskState()
        self.shows = copy.deepcopy(build_shows())
        self.trips = copy.deepcopy(build_trips())

    async def _emit(self) -> None:
        if self.on_change:
            await self.on_change(self.state.snapshot())

    def _code(self, prefix: str) -> str:
        self._n += 1
        return f"CUT-{prefix}{self._n:03d}"

    async def execute(self, name: str, arguments: str) -> str:
        try:
            args = json.loads(arguments or "{}")
        except json.JSONDecodeError:
            args = {}
        handler = getattr(self, name, None)
        if handler is None:
            return json.dumps({"error": f"unknown tool {name}"})
        result = await handler(**args)
        return result if isinstance(result, str) else json.dumps(result)

    async def search_docs(self, query: str) -> dict:
        hits = await store.search_async(query, k=3)
        return {"hits": hits, "demo": True}

    async def search_movies(self, query: str = "", city: str = "") -> dict:
        q = f"{query} {city}".strip()
        city_name = city.strip().title() if city.strip() else _city_from_text(q)
        if not city_name:
            city_name = "Indore"
        rows = [s for s in self.shows if s["city"] == city_name and _match(s, q)]
        if query.strip() and not rows:
            rows = [s for s in self.shows if _match(s, q)]
        if not rows:
            rows = [s for s in self.shows if s["city"] == city_name]
        now = [s for s in rows if s.get("status") != "coming_soon"]
        soon = [s for s in rows if s.get("status") == "coming_soon"]
        now.sort(key=lambda s: (0 if s["time"] >= "18:00" else 1, s["fill"] != "fast_filling", s["time"]))
        capped = now[:10] + soon[:3]
        return {
            "demo": True,
            "as_of": datetime.now().strftime("%a %d %b %Y, %I:%M %p"),
            "city": city_name,
            "results": [_public_show(s) for s in capped],
            "more": max(0, len(now) - 10),
        }

    async def book_movie(
        self,
        show_id: str = "",
        title: str = "",
        theater: str = "",
        time: str = "",
        city: str = "",
        seats: int = 2,
        name: str = "Guest",
        date: str | None = None,
    ) -> dict:
        seats = max(1, min(int(seats or 2), 6))
        show = next((s for s in self.shows if s["id"] == show_id), None)
        if show is None:
            wanted_time = _norm_time(time) if time else None
            city_name = city.strip().title() if city.strip() else _city_from_text(f"{title} {theater} {city}") or "Indore"
            needle = f"{title} {theater} {city_name}"
            candidates = [
                s
                for s in self.shows
                if _match(s, needle)
                and _time_close(s["time"], wanted_time)
                and (not city_name or s["city"] == city_name)
            ]
            if not candidates:
                candidates = [s for s in self.shows if _match(s, f"{title} {theater}") and _time_close(s["time"], wanted_time)]
            if len(candidates) == 1:
                show = candidates[0]
            elif candidates:
                return {
                    "ok": False,
                    "reason": "Several shows match. Ask which cinema or time, then book with show_id.",
                    "options": [_public_show(s) for s in candidates[:8]],
                }
            else:
                return {"ok": False, "reason": "No matching show. Search movies in that city first."}
        if show.get("status") == "coming_soon":
            hold = MovieHold(
                id=show["id"],
                title=show["title"],
                theater=show["theater"],
                city=show["city"],
                time=show["time"],
                date=show.get("opens") or "2026-12-18",
                seats=seats,
                screen=show["screen"],
                price=show["price"] * seats,
                code=self._code("W"),
                fill="coming_soon",
                status="coming_soon",
                confirmed=False,
            )
            self.state.movies.append(hold)
            await self._emit()
            ticket = asdict(hold)
            return {
                "ok": True,
                "demo": True,
                "waitlist": True,
                "reason": f"{show['title']} opens {show.get('opens', '18 Dec 2026')}. Advance booking is not live yet. I noted a reminder hold.",
                "ticket": ticket,
                "ticket_text": format_movie_ticket(ticket, waitlist=True),
            }
        if show["seats"] < seats:
            return {
                "ok": False,
                "reason": f"Only {show['seats']} seats left. That show is {show.get('fill', 'filling')}.",
                "show": _public_show(show),
            }
        show["seats"] -= seats
        cap = int(show.get("capacity") or 168)
        show["fill"] = "sold_out" if show["seats"] <= 0 else "almost_full" if show["seats"] / cap <= 0.08 else show["fill"]
        hold = MovieHold(
            id=show["id"],
            title=show["title"],
            theater=show["theater"],
            city=show["city"],
            time=show["time"],
            date=_parse_date(date),
            seats=seats,
            screen=show["screen"],
            price=show["price"] * seats,
            code=self._code("M"),
            fill=show["fill"],
            status="now_showing",
            confirmed=True,
        )
        self.state.movies.append(hold)
        await self._emit()
        ticket = asdict(hold)
        return {"ok": True, "demo": True, "ticket": ticket, "ticket_text": format_movie_ticket(ticket)}

    async def search_trips(
        self,
        origin: str = "",
        destination: str = "",
        kind: str = "",
        query: str = "",
    ) -> dict:
        q = f"{query} {origin} {destination} {kind}".strip()
        rows = [t for t in self.trips if _match(t, q)]
        if kind:
            k = kind.strip().lower()
            rows = [t for t in rows if t["kind"] == k] or [t for t in self.trips if t["kind"] == k]
        if not rows:
            rows = list(self.trips)
        return {
            "demo": True,
            "as_of": datetime.now().strftime("%a %d %b %Y, %I:%M %p"),
            "results": [_public_trip(t) for t in rows],
        }

    async def book_trip(
        self,
        trip_id: str,
        travelers: int = 1,
        name: str = "Guest",
        date: str | None = None,
    ) -> dict:
        travelers = max(1, min(int(travelers or 1), 6))
        trip = next((t for t in self.trips if t["id"] == trip_id), None)
        if trip is None:
            return {"ok": False, "reason": "Unknown trip_id. Search trips first."}
        if trip["seats"] < travelers:
            return {"ok": False, "reason": f"Only {trip['seats']} left on that option.", "trip": trip}
        trip["seats"] -= travelers
        hold = TripHold(
            id=trip["id"],
            kind=trip["kind"],
            title=trip["title"],
            detail=trip["detail"],
            date=_parse_date(date),
            travelers=travelers,
            price=trip["price"] * travelers,
            code=self._code("T"),
            confirmed=True,
        )
        self.state.trips.append(hold)
        await self._emit()
        booking = asdict(hold)
        return {"ok": True, "demo": True, "booking": booking, "ticket_text": format_trip_ticket(booking)}

    async def get_bookings(self) -> dict:
        snap = self.state.snapshot()
        snap["demo"] = True
        snap["ticket_texts"] = [format_movie_ticket(asdict(m), waitlist=not m.confirmed) for m in self.state.movies]
        snap["trip_texts"] = [format_trip_ticket(asdict(t)) for t in self.state.trips]
        return snap

    async def try_book_from_utterance(self, text: str) -> dict | None:
        """Book from a spoken sentence without waiting on the model."""
        a = re.sub(r"[^a-z0-9\s]+", "", text.lower()).strip()
        if re.search(r"\b(whats on|what is on|which shows|list|available)\b", a):
            return None
        if not re.search(r"\b(book|booking|tickets?|seats?)\b", a):
            return None

        title = None
        films = [
            (r"spider[\s-]*man|spiderman", "Spider-Man: Brand New Day"),
            (r"hanuman(\s+ansh)?|\bansh\b", "Hanuman Ansh"),
            (r"mirzapur", "Mirzapur: The Movie"),
            (r"\btoxic\b", "Toxic"),
            (r"dooms\s*day|avengers", "Avengers: Doomsday"),
        ]
        for pat, name in films:
            if re.search(pat, text, re.I):
                title = name
                break
        if not title:
            return {
                "ok": False,
                "spoken": "Which movie — Hanuman Ansh, Toxic, Mirzapur, or Spider-Man?",
            }

        theater = ""
        halls = [
            (r"treasure(\s+island)?|\bti\b", "Treasure Island"),
            (r"phoenix|citadel", "Phoenix"),
            (r"c[\s-]*21", "C21"),
            (r"nexus|central", "Nexus"),
            (r"velocity|miraj", "Velocity"),
            (r"malhar|rajhans", "Malhar"),
        ]
        for pat, name in halls:
            if re.search(pat, text, re.I):
                theater = name
                break

        screen = ""
        if re.search(r"\bimax\b", text, re.I):
            screen = "IMAX"
        elif re.search(r"4\s*dx", text, re.I):
            screen = "4DX"

        seats = 2
        num = re.search(r"\b([1-6])\b", a)
        if num:
            seats = int(num.group(1))
        else:
            for word, n in (("one", 1), ("two", 2), ("three", 3), ("four", 4), ("five", 5), ("six", 6)):
                if re.search(rf"\b{word}\b", a):
                    seats = n
                    break

        time_hit = re.search(r"\b(\d{1,2}:\d{2}|\d{1,2}\s*(?:am|pm))\b", text, re.I)
        wanted = _norm_time(time_hit.group(1)) if time_hit else None
        city = _city_from_text(text) or "Indore"

        cands = [s for s in self.shows if s["title"] == title and s["city"] == city]
        if theater:
            key = theater.lower()
            cands = [s for s in cands if key in s["theater"].lower() or key in s.get("search", "").lower()]
            if theater == "Phoenix" and city == "Indore":
                cands = [s for s in cands if "citadel" in s["theater"].lower() or "phoenix citadel" in s["theater"].lower()]
        if wanted:
            close = [s for s in cands if _time_close(s["time"], wanted)]
            if close:
                cands = close
        if screen:
            pref = [s for s in cands if s["screen"] == screen]
            if pref:
                cands = pref
            elif screen == "IMAX":
                four = [s for s in cands if s["screen"] == "4DX"]
                if four:
                    cands = four
                    screen = "4DX"
        live = [s for s in cands if s.get("status") != "coming_soon"]
        soon = [s for s in cands if s.get("status") == "coming_soon"]
        pool = live or soon
        if not wanted:
            evening = [s for s in pool if s["time"] >= "18:00"]
            if evening:
                pool = evening
        if not pool:
            return {
                "ok": False,
                "spoken": f"I don't have {title} at that hall in {city}. Try Phoenix, C21, or Treasure Island.",
            }
        if not theater and len({s["theater"] for s in pool}) > 1:
            sample = pool[:3]
            bits = "\n".join(
                f"{s['theater'].split(',')[0]}, {format_clock(s['time'])}, {s['screen']}" for s in sample
            )
            return {"ok": False, "spoken": f"A few halls for {title}.\n\n{bits}\n\nWhich cinema?"}
        open_pool = [
            s for s in pool if s.get("status") == "coming_soon" or int(s.get("seats") or 0) >= seats
        ]
        if not open_pool:
            return {
                "ok": False,
                "spoken": f"{title} is sold out at that hall. Try C21 or Phoenix, or a earlier show.",
            }
        show = sorted(open_pool, key=lambda s: (s["time"] < "18:00", s["time"]))[0]
        result = await self.book_movie(show_id=show["id"], seats=seats)
        ticket = result.get("ticket") or {}
        extra = ""
        if re.search(r"\bimax\b", text, re.I) and ticket.get("screen") and ticket["screen"] != "IMAX":
            extra = f"{ticket.get('theater', 'That hall')} has {ticket['screen']}, not IMAX."
        if result.get("ok") and ticket:
            result["spoken"] = format_movie_ticket(
                ticket, extra=extra, waitlist=bool(result.get("waitlist"))
            )
        else:
            result["spoken"] = result.get("reason") or "That show is full."
        return result
