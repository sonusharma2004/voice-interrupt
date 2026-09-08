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


CITY_ALIASES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"bengaluru|bangalore|\bblr\b", re.I), "Bengaluru"),
    (re.compile(r"\bmumbai\b|\bbombay\b|\bbom\b", re.I), "Mumbai"),
    (re.compile(r"\bdelhi\b|\bncr\b|\bsaket\b", re.I), "Delhi"),
    (re.compile(r"\bgoa\b|\bpanaji\b|\bmargao\b|(?<=\bto )go\b", re.I), "Goa"),
    (re.compile(r"\bindore\b|\bidr\b", re.I), "Indore"),
]

FILMS = [
    (re.compile(r"spider[\s-]*man|spiderman", re.I), "Spider-Man: Brand New Day"),
    (re.compile(r"hanuman(\s+ansh)?|\bansh\b", re.I), "Hanuman Ansh"),
    (re.compile(r"mirzapur", re.I), "Mirzapur: The Movie"),
    (re.compile(r"\btoxic\b", re.I), "Toxic"),
    (re.compile(r"dooms\s*day|avengers", re.I), "Avengers: Doomsday"),
]


def _cities_in_text(text: str) -> list[str]:
    hits: list[tuple[int, str]] = []
    for pat, name in CITY_ALIASES:
        for match in pat.finditer(text):
            hits.append((match.start(), name))
    hits.sort()
    names: list[str] = []
    for _, name in hits:
        if name not in names:
            names.append(name)
    return names


def _first_city(text: str) -> str:
    names = _cities_in_text(text)
    return names[0] if names else ""


def _city_from_text(text: str) -> str:
    return _first_city(text)


def _film_from_text(text: str) -> str | None:
    for pat, name in FILMS:
        if pat.search(text):
            return name
    return None


def _looks_like_trip(text: str) -> bool:
    a = re.sub(r"[^a-z0-9\s]+", "", text.lower())
    if _film_from_text(text):
        return False
    if re.search(
        r"\b(flight|flights|fly|flying|airfare|airport|plane|hotel|hotels|stay|resort|"
        r"package|indigo|vistara|airindia)\b",
        a,
    ):
        return True
    if re.search(r"\b(trip|trips|travel|travelling|traveling)\b", a) and (
        re.search(r"\b(book|plan|planning|search|find|go|going|package)\b", a) or _cities_in_text(text)
    ):
        return True
    if re.search(r"\bfrom\b.+\bto\b", a) and len(_cities_in_text(text)) >= 2:
        return True
    if len(_cities_in_text(text)) >= 2 and re.search(r"\bto\b", a):
        return True
    return False


def _route_from_text(text: str) -> tuple[str, str]:
    match = re.search(r"\bfrom\s+(.+?)\s+to\s+(.+)", text, re.I)
    if match:
        origin = _first_city(match.group(1))
        dest = _first_city(match.group(2))
        if origin or dest:
            return origin, dest
    to_hit = re.search(r"\bto\s+(.+)", text, re.I)
    if to_hit:
        dest = _first_city(to_hit.group(1))
        others = [c for c in _cities_in_text(text) if c != dest]
        if dest:
            origin = others[0] if others else "Indore"
            return origin, dest
    cities = _cities_in_text(text)
    if len(cities) >= 2:
        return cities[0], cities[1]
    if len(cities) == 1:
        if re.search(r"\b(hotel|hotels|stay|resort|in)\b", text, re.I):
            return "", cities[0]
        return "Indore", cities[0]
    return "", ""


def _people_from_text(text: str, default: int | None = None) -> int | None:
    a = re.sub(r"[^a-z0-9\s]+", "", text.lower())
    a = re.sub(
        r"\b(that|this|the|which|morning|evening|later|earlier|first|second|third)\s+one\b",
        " ",
        a,
    )
    # Whisper often glues "two seats" into one nonsense word.
    if re.search(r"\b(t+u+s*e+t+s*|twoseats?|tooseats?|2seats?|twosits?)\b", a):
        return 2
    if re.search(r"\b(threeseats?|3seats?)\b", a):
        return 3
    num = re.search(r"\b([1-6])\b", a)
    if num:
        return int(num.group(1))
    for word, n in (("one", 1), ("two", 2), ("three", 3), ("four", 4), ("five", 5), ("six", 6)):
        if re.search(rf"\b{word}\b", a):
            return n
    return default


def _trip_kind(text: str) -> str:
    a = text.lower()
    if re.search(r"\b(hotel|hotels|stay|resort|room)\b", a):
        return "hotel"
    if re.search(r"\b(package|weekend)\b", a):
        return "package"
    if re.search(r"\b(flight|flights|fly|flying|plane|airfare)\b", a):
        return "flight"
    if re.search(r"\bfrom\b.+\bto\b", a) or len(_cities_in_text(text)) >= 2:
        return "flight"
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


def _wanted_times(text: str) -> list[str]:
    """Parse spoken times including 6:35, 7-10 pm, 6 35 am, 635m, 1910."""
    found: list[str] = []
    text = re.sub(r"\b(\d{1,2})[-.](\d{2})\b", r"\1:\2", text or "")

    def add(hour: int, minute: int, mer: str) -> None:
        if minute > 59 or hour > 23 or hour < 0:
            return
        mer = re.sub(r"[^apm]", "", (mer or "").lower())
        if mer.startswith("p") and hour < 12:
            hour += 12
        elif mer.startswith("a") or mer == "m":
            if hour == 12:
                hour = 0
        clock = f"{hour:02d}:{minute:02d}"
        if clock not in found:
            found.append(clock)
        if not mer and 1 <= hour <= 11:
            later = f"{hour + 12:02d}:{minute:02d}"
            if later not in found:
                found.append(later)

    for match in re.finditer(r"\b(\d{1,2}):(\d{2})\s*(a\.?m\.?|p\.?m\.?|am|pm)?\b", text, re.I):
        add(int(match.group(1)), int(match.group(2)), match.group(3) or "")
    for match in re.finditer(r"\b(\d{1,2})\s+(\d{2})\s*(a\.?m\.?|p\.?m\.?|am|pm)?\b", text, re.I):
        add(int(match.group(1)), int(match.group(2)), match.group(3) or "")
    # Do not treat the minutes in 7:10 pm as a bare "10 pm".
    for match in re.finditer(
        r"(?<![:\d])(\d{1,2})\s*(a\.?m\.?|p\.?m\.?|am|pm)\b",
        text,
        re.I,
    ):
        add(int(match.group(1)), 0, match.group(2))
    for match in re.finditer(r"\b(\d{3,4})\s*(a\.?m\.?|p\.?m\.?|am|pm|m)?\b", text, re.I):
        digits = match.group(1)
        mer = match.group(2) or ""
        if len(digits) == 3:
            add(int(digits[0]), int(digits[1:]), mer)
        else:
            add(int(digits[:2]), int(digits[2:]), mer)
    return found


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


def _and_join(parts: list[str]) -> str:
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return f"{parts[0]} and {parts[1]}"
    return ", ".join(parts[:-1]) + f", and {parts[-1]}"


def _flight_legs(trip: dict[str, Any]) -> tuple[str, str]:
    times = re.findall(r"\b\d{1,2}:\d{2}\b", str(trip.get("detail") or ""))
    depart = format_clock(str(trip.get("time") or (times[0] if times else "")))
    arrive = format_clock(times[1]) if len(times) > 1 else ""
    return depart, arrive


def _short_hall(theater: str) -> str:
    return (theater or "").split(",")[0].strip()


def _sample_shows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(rows, key=lambda s: (s.get("time") or "99:99"))
    evening = [s for s in ordered if (s.get("time") or "") >= "18:00"]
    pool = evening or ordered
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, Any]] = []
    for show in pool:
        key = (show.get("theater") or "", show.get("time") or "")
        if key in seen:
            continue
        seen.add(key)
        out.append(show)
        if len(out) == 3:
            break
    return out


def speak_short_choice(
    rows: list[dict[str, Any]],
    *,
    kind: str,
    people: int | None,
    missed_time: bool = False,
) -> str:
    clocks: list[str] = []
    for row in rows[:4]:
        if row.get("kind") == "hotel":
            name = str(row.get("title") or "").split()[0]
            if name and name not in clocks:
                clocks.append(name)
            continue
        clock = format_clock(row.get("time")) if row.get("time") else ""
        if clock and clock not in clocks:
            clocks.append(clock)
    options = _and_join(clocks)
    prefix = "I didn't catch the time. " if missed_time else ""
    if kind == "movie":
        if people and options:
            return f"{prefix}Okay, {people} seats. Which show — {options}?"
        if options:
            return f"{prefix}Which show — {options}? And how many seats?"
        return f"{prefix}Which show, and how many seats?"
    if people and options:
        return f"{prefix}Okay, {people} people. Which time — {options}?"
    if options:
        return f"{prefix}Which time — {options}? And how many people?"
    return f"{prefix}Which time, and how many people?"


def speak_movie_options(rows: list[dict[str, Any]], title: str, seats: int | None) -> str:
    sample = _sample_shows(rows)
    if not sample:
        return f"I couldn't find {title} in this demo catalog."
    halls = {_short_hall(s.get("theater") or "") for s in sample}
    times = []
    for show in sample:
        clock = format_clock(show.get("time"))
        if clock not in times:
            times.append(clock)
    screen = sample[0].get("screen") or "2D"
    price = sample[0].get("price") or 0
    if len(halls) == 1:
        hall = next(iter(halls))
        lead = f"{title} is on at {hall}. I have {_and_join(times)}, {screen}, {price} rupees a seat."
    else:
        bits = [f"{_short_hall(s.get('theater') or '')} at {format_clock(s.get('time'))}" for s in sample]
        lead = f"{title} is playing at a few halls. {_and_join(bits)}. {price} rupees a seat."
    if seats:
        return f"{lead} I can hold {seats} — which show?"
    return f"{lead} How many seats, and which time?"


def speak_trip_options(rows: list[dict[str, Any]], origin: str = "", dest: str = "", people: int | None = None) -> str:
    rows = rows[:3]
    if not rows:
        return "I couldn't find that in this demo catalog."
    kind = rows[0].get("kind") or "trip"
    if kind == "hotel":
        city = dest or origin or "that city"
        bits = [f"{t['title']}, {format_clocks_in_text(str(t.get('detail') or ''))}, {t['price']} rupees a night" for t in rows]
        lead = f"In {city} I have {_and_join(bits)}."
        ask = "Which hotel, and for how many guests?" if not people else f"That's for {people}. Which hotel?"
        return f"{lead} {ask}"
    if kind == "package":
        t = rows[0]
        lead = f"I have {t['title']}. {format_clocks_in_text(str(t.get('detail') or ''))}, {t['price']} rupees."
        ask = "Want me to hold that, and for how many people?" if not people else f"That's for {people}. Should I hold it?"
        return f"{lead} {ask}"
    route = f"{origin} to {dest}" if origin and dest else "that route"
    if len(rows) == 1:
        leave, land = _flight_legs(rows[0])
        land_bit = f", landing at {land}" if land else ""
        lead = f"I have {rows[0]['title']} from {route} at {leave}{land_bit}, {rows[0]['price']} rupees."
    else:
        parts = [f"I found {len(rows)} flights from {route}."]
        for i, trip in enumerate(rows):
            leave, land = _flight_legs(trip)
            land_bit = f", landing at {land}" if land else ""
            bit = f"{trip['title']} at {leave}{land_bit}, {trip['price']} rupees"
            parts.append(f"There's {bit}." if i == 0 else f"{trip['title']} is at {leave}{land_bit}, {trip['price']} rupees.")
        lead = " ".join(parts)
    if people:
        return f"{lead} Which time should I hold for {people}?"
    return f"{lead} Which time works, and how many people?"


def speak_movie_confirm(ticket: dict[str, Any], extra: str = "") -> str:
    seats = int(ticket.get("seats") or 0)
    seat_word = "seat" if seats == 1 else "seats"
    fill = _fill_label(ticket.get("fill"))
    if ticket.get("status") == "coming_soon" or not ticket.get("confirmed", True):
        return (
            f"Advance seats aren't on sale yet for {ticket.get('title')}. "
            f"I left a reminder for {_short_hall(str(ticket.get('theater') or ''))}. "
            f"Your code is {ticket.get('code')}."
        )
    fill_bit = f" It's {fill}." if fill and fill not in {"seats open", ""} else ""
    spoken = (
        f"All set. I've held {seats} {seat_word} for {ticket.get('title')} at "
        f"{ticket.get('theater')}, {format_clock(ticket.get('time'))}, {ticket.get('screen')}. "
        f"That's {ticket.get('price')} rupees.{fill_bit} Confirmation code {ticket.get('code')}."
    )
    extra = extra.strip()
    if extra:
        spoken = f"{spoken} {extra}"
    return spoken


def speak_trip_confirm(booking: dict[str, Any]) -> str:
    travelers = int(booking.get("travelers") or 1)
    people = "person" if travelers == 1 else "people"
    detail = format_clocks_in_text(str(booking.get("detail") or ""))
    return (
        f"All set. I've held {booking.get('title')} for {travelers} {people}. "
        f"{detail}. That's {booking.get('price')} rupees. Confirmation code {booking.get('code')}."
    )


def _has_confirm(text: str) -> bool:
    return bool(
        re.search(
            r"\b(yes|yeah|yep|yup|ok|okay|sure|please|book it|book that|go ahead|"
            r"confirm|that one|this one|lock it|hold it|do it)\b",
            text,
            re.I,
        )
    )


def _looks_like_choice(text: str, pending: dict[str, Any]) -> bool:
    a = re.sub(r"[^a-z0-9\s]+", "", text.lower())
    if _people_from_text(text) is not None:
        return True
    if _has_confirm(text):
        return True
    if _wanted_times(text) or re.search(
        r"\b(\d{1,2}:\d{2}|\d{1,2}\s*(?:am|pm)|morning|evening|night|afternoon|early|later|first|second|third)\b",
        text,
        re.I,
    ):
        return True
    if pending.get("type") == "movie" and re.search(
        r"\b(seats?|tuseets?|twoseats?|tickets?)\b", a
    ):
        return True
    if pending.get("type") == "movie" and re.search(
        r"\b(phoenix|citadel|c21|treasure|\bti\b|nexus|velocity|malhar|imax|4dx)\b", a
    ):
        return True
    if pending.get("type") == "trip" and re.search(
        r"\b(indigo|vistara|air india|sayaji|radisson|taj|bloom|6e)\b", a
    ):
        return True
    return False


def _ordinal_index(text: str) -> int | None:
    a = text.lower()
    if re.search(r"\b(first|1st)\b", a):
        return 0
    if re.search(r"\b(second|2nd)\b", a):
        return 1
    if re.search(r"\b(third|3rd)\b", a):
        return 2
    return None


def _filter_by_time_words(rows: list[dict[str, Any]], text: str) -> list[dict[str, Any]]:
    if not rows:
        return rows
    a = re.sub(r"[^a-z0-9\s]+", "", text.lower())
    timed = [r for r in rows if r.get("time")]
    wanted = _wanted_times(text)
    if wanted:
        close = [r for r in timed if any(_time_close(r["time"], w) for w in wanted)]
        return close
    if re.search(r"\b(morning|early|earlier)\b", a):
        morning = [r for r in timed if r["time"] < "12:00"]
        return morning or [rows[0]]
    if re.search(r"\b(afternoon)\b", a):
        mid = [r for r in timed if "12:00" <= r["time"] < "17:00"]
        return mid or rows
    if re.search(r"\b(evening|night|later|last)\b", a):
        late = [r for r in timed if r["time"] >= "17:00"]
        return late or [rows[-1]]
    idx = _ordinal_index(text)
    if idx is not None and idx < len(rows):
        return [rows[idx]]
    return rows


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
        self.pending: dict[str, Any] | None = None

    def reset(self) -> None:
        self.state = DeskState()
        self.shows = copy.deepcopy(build_shows())
        self.trips = copy.deepcopy(build_trips())
        self.pending = None

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
                "confirm_text": speak_movie_confirm(ticket),
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
        return {"ok": True, "demo": True, "ticket": ticket, "confirm_text": speak_movie_confirm(ticket)}

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
        return {"ok": True, "demo": True, "booking": booking, "confirm_text": speak_trip_confirm(booking)}

    async def get_bookings(self) -> dict:
        snap = self.state.snapshot()
        snap["demo"] = True
        snap["summaries"] = [speak_movie_confirm(asdict(m)) for m in self.state.movies] + [
            speak_trip_confirm(asdict(t)) for t in self.state.trips
        ]
        return snap

    def _is_fresh_search(self, text: str) -> bool:
        pending = self.pending
        if not pending:
            return True
        if pending.get("type") == "movie" and _looks_like_trip(text) and not _film_from_text(text):
            return True
        if pending.get("type") == "trip" and _film_from_text(text):
            return True
        film = _film_from_text(text)
        if film and film != pending.get("title"):
            return True
        if _looks_like_trip(text):
            origin, dest = _route_from_text(text)
            if dest and pending.get("dest") and dest != pending.get("dest"):
                return True
            if origin and pending.get("origin") and origin != pending.get("origin") and re.search(r"\bfrom\b", text, re.I):
                return True
        return False

    def _theater_from_text(self, text: str) -> str:
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
                return name
        return ""

    def _filter_shows(self, rows: list[dict[str, Any]], text: str) -> list[dict[str, Any]]:
        theater = self._theater_from_text(text)
        if theater:
            key = theater.lower()
            filtered = [s for s in rows if key in s["theater"].lower() or key in s.get("search", "").lower()]
            if theater == "Phoenix":
                citadel = [s for s in filtered if "citadel" in s["theater"].lower()]
                if citadel:
                    filtered = citadel
            if filtered:
                rows = filtered
        if re.search(r"\bimax\b", text, re.I):
            pref = [s for s in rows if s.get("screen") == "IMAX"]
            rows = pref or [s for s in rows if s.get("screen") == "4DX"] or rows
        elif re.search(r"4\s*dx", text, re.I):
            pref = [s for s in rows if s.get("screen") == "4DX"]
            if pref:
                rows = pref
        return _filter_by_time_words(rows, text)

    def _filter_trips(self, rows: list[dict[str, Any]], text: str) -> list[dict[str, Any]]:
        a = text.lower()
        if re.search(r"\bindigo\b|\b6e\b", a):
            hit = [t for t in rows if "indigo" in t["title"].lower() or "6e" in t["title"].lower()]
            if hit:
                rows = hit
        if re.search(r"vistara", a):
            hit = [t for t in rows if "vistara" in t["title"].lower()]
            if hit:
                rows = hit
        if re.search(r"air india", a):
            hit = [t for t in rows if "air india" in t["title"].lower()]
            if hit:
                rows = hit
        for name in ("sayaji", "radisson", "taj", "bloom"):
            if re.search(rf"\b{name}\b", a):
                hit = [t for t in rows if name in t["title"].lower()]
                if hit:
                    rows = hit
        return _filter_by_time_words(rows, text)

    async def _finish_movie(self, show: dict[str, Any], seats: int, text: str) -> dict:
        result = await self.book_movie(show_id=show["id"], seats=seats)
        ticket = result.get("ticket") or {}
        extra = ""
        if re.search(r"\bimax\b", text, re.I) and ticket.get("screen") and ticket["screen"] != "IMAX":
            extra = f"{ticket.get('theater', 'That hall')} has {ticket['screen']}, not IMAX."
        self.pending = None
        if result.get("ok") and ticket:
            result["spoken"] = speak_movie_confirm(ticket, extra)
        else:
            result["spoken"] = result.get("reason") or "That show is full."
        return result

    async def _finish_trip(self, trip: dict[str, Any], people: int) -> dict:
        result = await self.book_trip(trip_id=trip["id"], travelers=people)
        booking = result.get("booking") or {}
        self.pending = None
        if result.get("ok") and booking:
            result["spoken"] = speak_trip_confirm(booking)
        else:
            result["spoken"] = result.get("reason") or "That option is full."
        return result

    async def _continue_pending(self, text: str) -> dict:
        pending = self.pending or {}
        people = _people_from_text(text)
        if people:
            pending["people"] = people
        mentioned_time = bool(_wanted_times(text)) or bool(
            re.search(r"\b(morning|evening|night|afternoon|early|later|first|second|third)\b", text, re.I)
        )
        if pending.get("type") == "movie":
            original = [s for s in self.shows if s["id"] in pending.get("ids", [])]
            rows = self._filter_shows(original, text)
            missed = mentioned_time and not rows
            if not rows:
                rows = original
            pending["ids"] = [s["id"] for s in rows]
            self.pending = pending
            seats = pending.get("people")
            if len(rows) == 1 and seats:
                return await self._finish_movie(rows[0], int(seats), text)
            if len(rows) == 1 and not seats:
                return {
                    "ok": False,
                    "spoken": f"The {format_clock(rows[0]['time'])} show. How many seats?",
                }
            ask_rows = [s for s in rows if s["id"] in pending.get("offered_ids", [])] or rows
            return {
                "ok": False,
                "spoken": speak_short_choice(ask_rows, kind="movie", people=seats, missed_time=missed),
            }

        original = [t for t in self.trips if t["id"] in pending.get("ids", [])]
        rows = self._filter_trips(original, text)
        missed = mentioned_time and not rows
        if not rows:
            rows = original
        pending["ids"] = [t["id"] for t in rows]
        self.pending = pending
        people = pending.get("people")
        if len(rows) == 1 and people:
            return await self._finish_trip(rows[0], int(people))
        if len(rows) == 1 and not people:
            leave, _ = _flight_legs(rows[0])
            return {
                "ok": False,
                "spoken": f"{rows[0]['title']} at {leave or 'that time'}. How many people?",
            }
        ask_rows = [t for t in rows if t["id"] in pending.get("offered_ids", [])] or rows
        return {
            "ok": False,
            "spoken": speak_short_choice(ask_rows, kind="trip", people=people, missed_time=missed),
        }

    async def _offer_trip(self, text: str) -> dict:
        kind = _trip_kind(text)
        origin, dest = _route_from_text(text)
        people = _people_from_text(text)
        if kind == "flight" and not origin and not dest:
            return {
                "ok": False,
                "spoken": "Where from and to? I can search Indore, Mumbai, Delhi, Goa, and Bengaluru.",
            }
        if not kind and not origin and not dest:
            return {
                "ok": False,
                "spoken": "Where should I look? I have flights and hotels for Indore, Mumbai, Delhi, Goa, and Bengaluru.",
            }

        rows = list(self.trips)
        if kind:
            rows = [t for t in rows if t["kind"] == kind]
        if kind == "hotel":
            city = dest or origin
            if city:
                rows = [t for t in rows if t.get("destination") == city]
        else:
            if origin:
                rows = [t for t in rows if t.get("origin") == origin]
            if dest:
                rows = [t for t in rows if t.get("destination") == dest]
        rows = self._filter_trips(rows, text)

        if not rows:
            alt = [t for t in self.trips if t["kind"] == "flight" and t.get("origin") == (origin or "Indore")][:3]
            if origin and dest:
                spoken = f"I don't have {origin} to {dest} in this demo."
            else:
                spoken = "I don't have that option in this demo."
            if alt:
                spoken = f"{spoken} {speak_trip_options(alt, origin or 'Indore', alt[0].get('destination') or '')}"
            return {"ok": False, "spoken": spoken}

        unique = len(rows) == 1
        time_hit = bool(re.search(r"\b(\d{1,2}:\d{2}|\d{1,2}\s*(?:am|pm)|morning|evening|afternoon)\b", text, re.I))
        if unique and people and (time_hit or kind in {"hotel", "package"}):
            return await self._finish_trip(rows[0], people)

        self.pending = {
            "type": "trip",
            "ids": [t["id"] for t in rows[:4]],
            "offered_ids": [t["id"] for t in rows[:3]],
            "people": people,
            "origin": origin,
            "dest": dest,
        }
        return {"ok": False, "spoken": speak_trip_options(rows, origin, dest, people)}

    async def _offer_movie(self, text: str) -> dict | None:
        a = re.sub(r"[^a-z0-9\s]+", "", text.lower()).strip()
        if re.search(r"\b(whats on|what is on|which shows|list|available)\b", a):
            return None
        if not re.search(r"\b(book|booking|tickets?|seats?)\b", a):
            return None

        title = _film_from_text(text)
        if not title:
            return {
                "ok": False,
                "spoken": "Which movie — Hanuman Ansh, Toxic, Mirzapur, or Spider-Man?",
            }

        seats = _people_from_text(text)
        city = _city_from_text(text) or "Indore"
        cands = [s for s in self.shows if s["title"] == title and s["city"] == city]
        cands = self._filter_shows(cands, text)
        live = [s for s in cands if s.get("status") != "coming_soon"]
        soon = [s for s in cands if s.get("status") == "coming_soon"]
        pool = live or soon
        if not pool:
            return {
                "ok": False,
                "spoken": f"I don't have {title} at that hall in {city}. Phoenix, C21, or Treasure Island might.",
            }

        theater = self._theater_from_text(text)
        time_hit = bool(re.search(r"\b(\d{1,2}:\d{2}|\d{1,2}\s*(?:am|pm))\b", text, re.I))
        if theater and time_hit and seats and len(pool) == 1:
            return await self._finish_movie(pool[0], seats, text)

        ordered = sorted(pool, key=lambda s: s.get("time") or "99:99")
        self.pending = {
            "type": "movie",
            "ids": [s["id"] for s in ordered[:8]],
            "offered_ids": [s["id"] for s in _sample_shows(pool)],
            "people": seats,
            "title": title,
        }
        extra = ""
        if re.search(r"\bimax\b", text, re.I) and all(s.get("screen") != "IMAX" for s in pool):
            extra = f" {_short_hall(pool[0]['theater'])} has {pool[0].get('screen')}, not IMAX."
        return {"ok": False, "spoken": speak_movie_options(pool, title, seats) + extra}

    async def try_book_from_utterance(self, text: str) -> dict | None:
        """Offer options, then hold only after they pick a slot and party size."""
        if self.pending and not self._is_fresh_search(text) and _looks_like_choice(text, self.pending):
            return await self._continue_pending(text)
        if _looks_like_trip(text):
            return await self._offer_trip(text)
        return await self._offer_movie(text)
