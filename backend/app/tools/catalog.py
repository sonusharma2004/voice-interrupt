from __future__ import annotations

from datetime import datetime

# Now showing as of 8 Sep 2026. Coming soon is advance-only.

CINEMAS = [
    {"id": "phoenix", "name": "INOX Phoenix Citadel Mall, Indore", "city": "Indore", "imax": True, "fourdx": True, "keys": "phoenix citadel inox"},
    {"id": "c21", "name": "INOX C21 Mall, Indore", "city": "Indore", "imax": False, "fourdx": False, "keys": "c21 c-21 inox"},
    {"id": "ti", "name": "PVR Treasure Island Mall, Indore", "city": "Indore", "imax": False, "fourdx": True, "keys": "ti treasure island pvr tukoganj"},
    {"id": "nexus", "name": "INOX Nexus Indore Central, Indore", "city": "Indore", "imax": False, "fourdx": False, "keys": "nexus central regal inox"},
    {"id": "velocity", "name": "Miraj Cinemas Velocity III, Indore", "city": "Indore", "imax": False, "fourdx": False, "keys": "velocity miraj"},
    {"id": "malhar", "name": "Rajhans Cinemas Malhar Mega Mall, Indore", "city": "Indore", "imax": False, "fourdx": False, "keys": "malhar rajhans"},
    {"id": "palladium", "name": "PVR Phoenix Palladium, Mumbai", "city": "Mumbai", "imax": True, "fourdx": True, "keys": "palladium phoenix lower parel pvr"},
    {"id": "rcity", "name": "INOX R City Ghatkopar, Mumbai", "city": "Mumbai", "imax": False, "fourdx": False, "keys": "rcity r city ghatkopar inox"},
    {"id": "saket", "name": "PVR Select Citywalk Saket, Delhi", "city": "Delhi", "imax": True, "fourdx": False, "keys": "saket citywalk pvr"},
    {"id": "pacific", "name": "PVR Pacific Mall Tagore Garden, Delhi", "city": "Delhi", "imax": False, "fourdx": True, "keys": "pacific tagore pvr"},
    {"id": "panaji", "name": "INOX Panaji, Goa", "city": "Goa", "imax": False, "fourdx": False, "keys": "panaji panjim inox"},
    {"id": "margao", "name": "INOX Margao, Goa", "city": "Goa", "imax": False, "fourdx": False, "keys": "margao madgaon inox"},
    {"id": "orion", "name": "PVR Orion Mall Bengaluru", "city": "Bengaluru", "imax": True, "fourdx": True, "keys": "orion rajajinagar pvr bangalore bengaluru"},
]

NOW_SHOWING = [
    {
        "slug": "hanuman-ansh",
        "title": "Hanuman Ansh",
        "language": "Hindi",
        "rating": "U",
        "hot": True,
        "screens": ("2D",),
        "price_2d": 210,
        "keys": "hanuman ansh neem karoli",
    },
    {
        "slug": "toxic",
        "title": "Toxic",
        "language": "Hindi",
        "rating": "UA16+",
        "hot": False,
        "screens": ("2D", "IMAX"),
        "price_2d": 280,
        "price_imax": 430,
        "keys": "toxic yash kgf",
    },
    {
        "slug": "mirzapur",
        "title": "Mirzapur: The Movie",
        "language": "Hindi",
        "rating": "A",
        "hot": True,
        "screens": ("2D",),
        "price_2d": 260,
        "keys": "mirzapur guddu kaleen",
    },
    {
        "slug": "spiderman",
        "title": "Spider-Man: Brand New Day",
        "language": "English",
        "rating": "UA13+",
        "hot": True,
        "screens": ("2D", "IMAX", "4DX"),
        "price_2d": 320,
        "price_imax": 520,
        "price_4dx": 580,
        "keys": "spider spiderman spider-man brand new day",
    },
]

COMING_SOON = [
    {
        "slug": "doomsday",
        "title": "Avengers: Doomsday",
        "language": "English",
        "rating": "TBA",
        "opens": "2026-12-18",
        "screens": ("IMAX", "2D"),
        "price_2d": 350,
        "price_imax": 650,
        "keys": "doomsday avengers doom dooms day",
    },
]

# Slightly messy slots so it does not look generated on a grid.
SLOTS = {
    "phoenix": ["10:20", "13:15", "16:05", "19:10", "22:20"],
    "c21": ["10:40", "13:35", "16:25", "19:20", "22:05"],
    "ti": ["11:00", "13:50", "16:45", "19:40", "22:30"],
    "nexus": ["10:55", "14:05", "16:50", "19:55", "22:10"],
    "velocity": ["11:10", "14:20", "17:00", "20:05", "22:40"],
    "malhar": ["10:30", "13:20", "16:10", "19:00", "21:50"],
    "palladium": ["11:20", "14:40", "18:00", "21:15"],
    "rcity": ["12:00", "15:10", "18:30", "21:40"],
    "saket": ["11:05", "14:25", "17:50", "21:05"],
    "pacific": ["12:15", "15:30", "18:45", "21:50"],
    "panaji": ["13:00", "16:20", "19:30"],
    "margao": ["14:10", "17:40", "20:50"],
    "orion": ["11:30", "15:00", "18:20", "21:25"],
}


def _capacity(screen: str) -> int:
    if screen == "IMAX":
        return 92
    if screen == "4DX":
        return 64
    return 168


def _seats_left(title: str, time: str, screen: str, cinema_id: str) -> int:
    hour = int(time[:2])
    cap = _capacity(screen)
    # Evening and weekend-prime fill faster; Toxic is cooler.
    taken = 28 + hour * 3
    if title == "Hanuman Ansh":
        taken += 55
    if title.startswith("Mirzapur"):
        taken += 48
    if title.startswith("Spider-Man"):
        taken += 40
    if title == "Toxic":
        taken -= 20
    if screen in {"IMAX", "4DX"}:
        taken += 18
    if cinema_id in {"phoenix", "ti", "palladium", "saket"}:
        taken += 12
    left = cap - taken
    if cinema_id in {"ti", "phoenix", "c21"} and screen in {"IMAX", "4DX"}:
        left = max(left, 8)
    if hour < 13:
        left = max(left, 36 if screen == "2D" else 14)
    return min(cap, max(0, left))


def _fill(seats: int, capacity: int) -> str:
    if seats <= 0:
        return "sold_out"
    ratio = seats / capacity
    if ratio <= 0.08:
        return "almost_full"
    if ratio <= 0.28:
        return "fast_filling"
    return "available"


def _price(movie: dict, screen: str) -> int:
    key = { "2D": "price_2d", "IMAX": "price_imax", "4DX": "price_4dx" }.get(screen, "price_2d")
    return int(movie.get(key) or movie.get("price_2d") or 250)


def _show(
    movie: dict,
    cinema: dict,
    time: str,
    screen: str,
    *,
    status: str = "now_showing",
    opens: str = "",
) -> dict:
    seats = 0 if status == "coming_soon" else _seats_left(movie["title"], time, screen, cinema["id"])
    cap = _capacity(screen)
    sid = f"{movie['slug']}-{cinema['id']}-{time.replace(':', '')}-{screen.lower()}"
    return {
        "id": sid,
        "title": movie["title"],
        "theater": cinema["name"],
        "city": cinema["city"],
        "time": time,
        "screen": screen,
        "language": movie["language"],
        "rating": movie.get("rating", ""),
        "price": _price(movie, screen),
        "seats": seats,
        "capacity": cap,
        "fill": "coming_soon" if status == "coming_soon" else _fill(seats, cap),
        "status": status,
        "opens": opens,
        "as_of": datetime.now().strftime("%d %b, %I:%M %p"),
        "search": f"{movie.get('keys', '')} {cinema.get('keys', '')} {cinema['city']}",
    }


def build_shows() -> list[dict]:
    rows: list[dict] = []
    for cinema in CINEMAS:
        times = SLOTS[cinema["id"]]
        for movie in NOW_SHOWING:
            screens = [s for s in movie["screens"] if s == "2D" or (s == "IMAX" and cinema["imax"]) or (s == "4DX" and cinema["fourdx"])]
            if not screens:
                screens = ["2D"]
            # Not every film on every slot — skip Toxic's last show in smaller halls.
            use_times = times
            if movie["slug"] == "toxic" and cinema["id"] in {"velocity", "malhar", "margao"}:
                use_times = times[1:4]
            if movie["slug"] == "spiderman" and cinema["city"] == "Goa":
                use_times = times[-2:]
            for time in use_times:
                screen = "2D"
                if time >= "18:00" and "IMAX" in screens and cinema["imax"]:
                    screen = "IMAX"
                elif time >= "19:00" and "4DX" in screens and cinema["fourdx"] and movie["slug"] == "spiderman":
                    screen = "4DX"
                rows.append(_show(movie, cinema, time, screen))
        # Advance listing for Doomsday at premium halls only.
        if cinema["imax"] or cinema["id"] in {"phoenix", "ti", "c21"}:
            upcoming = COMING_SOON[0]
            screen = "IMAX" if cinema["imax"] else "2D"
            rows.append(_show(upcoming, cinema, "19:00", screen, status="coming_soon", opens=upcoming["opens"]))
    return rows


def build_trips() -> list[dict]:
    return [
        {"id": "flight-idr-bom-0635", "kind": "flight", "title": "IndiGo 6E 6182", "detail": "Indore to Mumbai, 06:35–08:00", "origin": "Indore", "destination": "Mumbai", "time": "06:35", "price": 4200, "seats": 7},
        {"id": "flight-idr-bom-1520", "kind": "flight", "title": "Air India AI 440", "detail": "Indore to Mumbai, 15:20–16:50", "origin": "Indore", "destination": "Mumbai", "time": "15:20", "price": 5100, "seats": 5},
        {"id": "flight-idr-del-0715", "kind": "flight", "title": "IndiGo 6E 2031", "detail": "Indore to Delhi, 07:15–08:55", "origin": "Indore", "destination": "Delhi", "time": "07:15", "price": 5600, "seats": 6},
        {"id": "flight-idr-del-1840", "kind": "flight", "title": "Vistara UK 651", "detail": "Indore to Delhi, 18:40–20:20", "origin": "Indore", "destination": "Delhi", "time": "18:40", "price": 6400, "seats": 4},
        {"id": "flight-idr-goa-1010", "kind": "flight", "title": "IndiGo 6E 745", "detail": "Indore to Goa, 10:10–12:05", "origin": "Indore", "destination": "Goa", "time": "10:10", "price": 6800, "seats": 5},
        {"id": "flight-bom-goa-0825", "kind": "flight", "title": "IndiGo 6E 531", "detail": "Mumbai to Goa, 08:25–09:40", "origin": "Mumbai", "destination": "Goa", "time": "08:25", "price": 3900, "seats": 8},
        {"id": "flight-del-goa-1130", "kind": "flight", "title": "Air India AI 803", "detail": "Delhi to Goa, 11:30–14:05", "origin": "Delhi", "destination": "Goa", "time": "11:30", "price": 7200, "seats": 6},
        {"id": "flight-blr-goa-0710", "kind": "flight", "title": "IndiGo 6E 214", "detail": "Bengaluru to Goa, 07:10–08:25", "origin": "Bengaluru", "destination": "Goa", "time": "07:10", "price": 6400, "seats": 6},
        {"id": "flight-blr-goa-1945", "kind": "flight", "title": "IndiGo 6E 901", "detail": "Bengaluru to Goa, 19:45–21:00", "origin": "Bengaluru", "destination": "Goa", "time": "19:45", "price": 8100, "seats": 5},
        {"id": "flight-blr-idr-0715", "kind": "flight", "title": "IndiGo 6E 2281", "detail": "Bengaluru to Indore, 07:15–08:50", "origin": "Bengaluru", "destination": "Indore", "time": "07:15", "price": 5900, "seats": 6},
        {"id": "flight-blr-idr-1855", "kind": "flight", "title": "Vistara UK 877", "detail": "Bengaluru to Indore, 18:55–20:30", "origin": "Bengaluru", "destination": "Indore", "time": "18:55", "price": 7200, "seats": 5},
        {"id": "flight-idr-blr-0620", "kind": "flight", "title": "IndiGo 6E 2282", "detail": "Indore to Bengaluru, 06:20–07:55", "origin": "Indore", "destination": "Bengaluru", "time": "06:20", "price": 5800, "seats": 6},
        {"id": "flight-idr-blr-1910", "kind": "flight", "title": "Air India AI 616", "detail": "Indore to Bengaluru, 19:10–20:45", "origin": "Indore", "destination": "Bengaluru", "time": "19:10", "price": 7000, "seats": 4},
        {"id": "hotel-sayaji-indore", "kind": "hotel", "title": "Sayaji Hotel Indore", "detail": "Vijay Nagar, breakfast included", "origin": "", "destination": "Indore", "time": "", "price": 6200, "seats": 8},
        {"id": "hotel-radisson-indore", "kind": "hotel", "title": "Radisson Blu Indore", "detail": "Ring Road, pool and breakfast", "origin": "", "destination": "Indore", "time": "", "price": 7800, "seats": 5},
        {"id": "hotel-taj-goa", "kind": "hotel", "title": "Taj Holiday Village Goa", "detail": "Candolim, breakfast included", "origin": "", "destination": "Goa", "time": "", "price": 9200, "seats": 4},
        {"id": "hotel-bloom-goa", "kind": "hotel", "title": "Bloom Hotel Calangute", "detail": "Calangute, room only", "origin": "", "destination": "Goa", "time": "", "price": 4200, "seats": 6},
        {"id": "pkg-goa-idr", "kind": "package", "title": "Goa weekend from Indore", "detail": "2 nights, flights plus Bloom Hotel", "origin": "Indore", "destination": "Goa", "time": "", "price": 21400, "seats": 4},
    ]
