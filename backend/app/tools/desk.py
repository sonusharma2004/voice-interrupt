from __future__ import annotations

import copy
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable

from app.rag.store import store

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
            "description": "List demo movie shows (BookMyShow-style). Filter by title, city, or theater.",
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
            "description": "List demo flights, hotels, and packages (MakeMyTrip-style).",
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


SHOWS = [
    {
        "id": "dune-pvr-1600",
        "title": "Dune: Part Two",
        "theater": "PVR Phoenix Bengaluru",
        "city": "Bengaluru",
        "time": "16:00",
        "screen": "2D",
        "price": 280,
        "seats": 8,
    },
    {
        "id": "dune-pvr-1900",
        "title": "Dune: Part Two",
        "theater": "PVR Phoenix Bengaluru",
        "city": "Bengaluru",
        "time": "19:00",
        "screen": "IMAX",
        "price": 450,
        "seats": 8,
    },
    {
        "id": "dune-pvr-2130",
        "title": "Dune: Part Two",
        "theater": "PVR Phoenix Bengaluru",
        "city": "Bengaluru",
        "time": "21:30",
        "screen": "2D",
        "price": 280,
        "seats": 8,
    },
    {
        "id": "deadpool-inox-1800",
        "title": "Deadpool & Wolverine",
        "theater": "INOX Garuda Mall Bengaluru",
        "city": "Bengaluru",
        "time": "18:00",
        "screen": "2D",
        "price": 320,
        "seats": 8,
    },
    {
        "id": "deadpool-inox-2115",
        "title": "Deadpool & Wolverine",
        "theater": "INOX Garuda Mall Bengaluru",
        "city": "Bengaluru",
        "time": "21:15",
        "screen": "2D",
        "price": 320,
        "seats": 8,
    },
    {
        "id": "stree-pvr-1715",
        "title": "Stree 2",
        "theater": "PVR Forum Mumbai",
        "city": "Mumbai",
        "time": "17:15",
        "screen": "2D",
        "price": 250,
        "seats": 8,
    },
    {
        "id": "stree-pvr-2030",
        "title": "Stree 2",
        "theater": "PVR Forum Mumbai",
        "city": "Mumbai",
        "time": "20:30",
        "screen": "2D",
        "price": 250,
        "seats": 8,
    },
]

TRIPS = [
    {
        "id": "flight-blr-goa-0710",
        "kind": "flight",
        "title": "IndiGo 6E 214",
        "detail": "Bengaluru to Goa, 07:10–08:25",
        "origin": "Bengaluru",
        "destination": "Goa",
        "time": "07:10",
        "price": 6400,
        "seats": 6,
    },
    {
        "id": "flight-blr-goa-1420",
        "kind": "flight",
        "title": "Air India AI 657",
        "detail": "Bengaluru to Goa, 14:20–15:40",
        "origin": "Bengaluru",
        "destination": "Goa",
        "time": "14:20",
        "price": 7200,
        "seats": 6,
    },
    {
        "id": "flight-blr-goa-1945",
        "kind": "flight",
        "title": "IndiGo 6E 901",
        "detail": "Bengaluru to Goa, 19:45–21:00",
        "origin": "Bengaluru",
        "destination": "Goa",
        "time": "19:45",
        "price": 8100,
        "seats": 6,
    },
    {
        "id": "flight-del-bom-0800",
        "kind": "flight",
        "title": "Vistara UK 995",
        "detail": "Delhi to Mumbai, 08:00–10:15",
        "origin": "Delhi",
        "destination": "Mumbai",
        "time": "08:00",
        "price": 9100,
        "seats": 6,
    },
    {
        "id": "hotel-taj-goa",
        "kind": "hotel",
        "title": "Taj Holiday Village Goa",
        "detail": "Candolim, breakfast included",
        "origin": "",
        "destination": "Goa",
        "time": "",
        "price": 9200,
        "seats": 4,
    },
    {
        "id": "hotel-bloom-goa",
        "kind": "hotel",
        "title": "Bloom Hotel Calangute",
        "detail": "Calangute, room only",
        "origin": "",
        "destination": "Goa",
        "time": "",
        "price": 4200,
        "seats": 5,
    },
    {
        "id": "pkg-goa-weekend",
        "kind": "package",
        "title": "Goa weekend 2 nights",
        "detail": "Flights from Bengaluru plus Bloom Hotel",
        "origin": "Bengaluru",
        "destination": "Goa",
        "time": "",
        "price": 18900,
        "seats": 4,
    },
]


@dataclass
class MovieHold:
    id: str
    title: str
    theater: str
    time: str
    date: str
    seats: int
    screen: str
    price: int
    code: str
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


def _hay(item: dict[str, Any]) -> str:
    return " ".join(str(item.get(k, "")) for k in ("id", "title", "theater", "city", "screen", "kind", "detail", "origin", "destination")).lower()


def _match(item: dict[str, Any], query: str) -> bool:
    if not query.strip():
        return True
    blob = _hay(item)
    terms = [t for t in re.findall(r"[a-z0-9]+", query.lower()) if len(t) > 1]
    aliases = {"bangalore": "bengaluru", "blr": "bengaluru", "bom": "mumbai", "del": "delhi", "goa": "goa"}
    mapped = [aliases.get(t, t) for t in terms]
    return all(t in blob for t in mapped)


class DeskTools:
    def __init__(self, on_change: Callable[[dict], Awaitable[None]] | None = None) -> None:
        self.state = DeskState()
        self.on_change = on_change
        self.shows = copy.deepcopy(SHOWS)
        self.trips = copy.deepcopy(TRIPS)
        self._n = 0

    def reset(self) -> None:
        self.state = DeskState()
        self.shows = copy.deepcopy(SHOWS)
        self.trips = copy.deepcopy(TRIPS)

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
        rows = [s for s in self.shows if _match(s, q)]
        if not rows:
            rows = list(self.shows)
        return {"demo": True, "results": rows}

    async def book_movie(
        self,
        show_id: str = "",
        title: str = "",
        theater: str = "",
        time: str = "",
        seats: int = 2,
        name: str = "Guest",
        date: str | None = None,
    ) -> dict:
        seats = max(1, min(int(seats or 2), 6))
        show = next((s for s in self.shows if s["id"] == show_id), None)
        if show is None:
            wanted_time = _norm_time(time) if time else None
            candidates = [
                s
                for s in self.shows
                if _match(s, f"{title} {theater}") and (not wanted_time or s["time"] == wanted_time)
            ]
            if len(candidates) == 1:
                show = candidates[0]
            elif candidates:
                return {
                    "ok": False,
                    "reason": "Several shows match. Ask which time or theater, then book with show_id.",
                    "options": candidates,
                }
            else:
                return {"ok": False, "reason": "No matching show in the demo catalog. Search movies first."}
        if show["seats"] < seats:
            return {
                "ok": False,
                "reason": f"Only {show['seats']} seats left for that show.",
                "show": show,
            }
        show["seats"] -= seats
        hold = MovieHold(
            id=show["id"],
            title=show["title"],
            theater=show["theater"],
            time=show["time"],
            date=_parse_date(date),
            seats=seats,
            screen=show["screen"],
            price=show["price"] * seats,
            code=self._code("M"),
            confirmed=True,
        )
        self.state.movies.append(hold)
        await self._emit()
        return {"ok": True, "demo": True, "ticket": asdict(hold)}

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
        return {"demo": True, "results": rows}

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
            date=_parse_date(date) if date or trip["kind"] != "hotel" else _parse_date(date),
            travelers=travelers,
            price=trip["price"] * travelers,
            code=self._code("T"),
            confirmed=True,
        )
        self.state.trips.append(hold)
        await self._emit()
        return {"ok": True, "demo": True, "booking": asdict(hold)}

    async def get_bookings(self) -> dict:
        snap = self.state.snapshot()
        snap["demo"] = True
        return snap
