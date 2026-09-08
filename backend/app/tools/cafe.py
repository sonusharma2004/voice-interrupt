from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Awaitable

from app.rag.store import store

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "search_docs",
            "description": "Search café menu, hours, house rules, and booking policy.",
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
            "name": "add_to_order",
            "description": "Add a menu item to the current ticket.",
            "parameters": {
                "type": "object",
                "properties": {
                    "item": {"type": "string"},
                    "qty": {"type": "integer", "default": 1},
                    "mods": {"type": "string", "description": "oat milk, extra shot, no butter…"},
                },
                "required": ["item"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_order",
            "description": "Read back the current ticket.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "confirm_order",
            "description": "Lock the ticket as sent to the bar.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_availability",
            "description": "See if a table slot is free. Time like '10:00' or '10am'. Date like 'tomorrow' or YYYY-MM-DD.",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {"type": "string"},
                    "time": {"type": "string"},
                    "party": {"type": "integer"},
                },
                "required": ["time", "party"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "book_table",
            "description": "Hold a table after availability is confirmed.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "party": {"type": "integer"},
                    "date": {"type": "string"},
                    "time": {"type": "string"},
                },
                "required": ["name", "party", "time"],
            },
        },
    },
]


@dataclass
class OrderLine:
    item: str
    qty: int = 1
    mods: str = ""


@dataclass
class Booking:
    name: str
    party: int
    date: str
    time: str


@dataclass
class CafeState:
    lines: list[OrderLine] = field(default_factory=list)
    confirmed: bool = False
    bookings: list[Booking] = field(default_factory=list)
    # Shared across sessions in-process so two demo tabs contend for slots.
    _slots: dict[str, int] = field(default_factory=dict)

    def snapshot(self) -> dict[str, Any]:
        return {
            "lines": [asdict(x) for x in self.lines],
            "confirmed": self.confirmed,
            "bookings": [asdict(b) for b in self.bookings],
        }


# Module-level occupancy so bookings persist for the process lifetime.
_OCCUPANCY: dict[str, int] = {}
MAX_GUESTS_PER_SLOT = 8


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


def _norm_time(raw: str) -> str:
    text = raw.strip().lower().replace(" ", "")
    text = text.replace(".", "")
    meridiem = ""
    if text.endswith("am") or text.endswith("pm"):
        meridiem = text[-2:]
        text = text[:-2]
    if ":" in text:
        hh, mm = text.split(":", 1)
    else:
        hh, mm = text, "00"
    hour = int(hh)
    minute = int(mm[:2] or "0")
    if meridiem == "pm" and hour < 12:
        hour += 12
    if meridiem == "am" and hour == 12:
        hour = 0
    return f"{hour:02d}:{minute:02d}"


def _slot_ok(time_hhmm: str) -> bool:
    hour, minute = map(int, time_hhmm.split(":"))
    if minute not in (0, 30):
        return False
    minutes = hour * 60 + minute
    return 8 * 60 <= minutes <= 14 * 60


class CafeTools:
    def __init__(self, on_change: Callable[[dict], Awaitable[None]] | None = None) -> None:
        self.state = CafeState()
        self.on_change = on_change

    async def _emit(self) -> None:
        if self.on_change:
            await self.on_change(self.state.snapshot())

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
        return {"hits": hits}

    async def add_to_order(self, item: str, qty: int = 1, mods: str = "") -> dict:
        self.state.confirmed = False
        self.state.lines.append(OrderLine(item=item, qty=int(qty or 1), mods=mods or ""))
        await self._emit()
        return {"ok": True, "order": self.state.snapshot()}

    async def get_order(self) -> dict:
        return self.state.snapshot()

    async def confirm_order(self) -> dict:
        if not self.state.lines:
            return {"ok": False, "reason": "empty ticket"}
        self.state.confirmed = True
        await self._emit()
        return {"ok": True, "order": self.state.snapshot()}

    async def check_availability(self, time: str, party: int, date: str | None = None) -> dict:
        party = int(party)
        if party < 2 or party > 6:
            return {"ok": False, "reason": "We book tables for 2 to 6. Solo guests sit at the bar."}
        try:
            hhmm = _norm_time(time)
        except Exception:
            return {"ok": False, "reason": "Could not read that time."}
        if not _slot_ok(hhmm):
            return {"ok": False, "reason": "We book on the hour or half-hour from 8:00 to 2:00."}
        day = _parse_date(date)
        key = f"{day}T{hhmm}"
        used = _OCCUPANCY.get(key, 0)
        free = used + party <= MAX_GUESTS_PER_SLOT
        return {
            "ok": free,
            "date": day,
            "time": hhmm,
            "party": party,
            "remaining_seats": max(0, MAX_GUESTS_PER_SLOT - used),
            "reason": None if free else "That slot is full.",
        }

    async def book_table(self, name: str, party: int, time: str, date: str | None = None) -> dict:
        check = await self.check_availability(time=time, party=party, date=date)
        if not check.get("ok"):
            return check
        key = f"{check['date']}T{check['time']}"
        _OCCUPANCY[key] = _OCCUPANCY.get(key, 0) + int(party)
        booking = Booking(name=name, party=int(party), date=check["date"], time=check["time"])
        self.state.bookings.append(booking)
        await self._emit()
        return {"ok": True, "booking": asdict(booking)}
