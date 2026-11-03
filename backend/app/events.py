"""Birthdays, holidays and other dates Bit should remember and celebrate.
Fixed national holidays live in holidays_uz.json (edit freely). Moving holidays (Ramazon/Qurbon hayit) change
every year: add them with a full date, e.g. "Bit, 2027-03-10 Ramazon hayiti deb eslab qol"."""
import json
from datetime import date, timedelta
from pathlib import Path

_HOLIDAYS_FILE = Path(__file__).with_name("holidays_uz.json")


def parse_date(text: str) -> tuple[int | None, int, int]:
    """'MM-DD' or 'YYYY-MM-DD' -> (year|None, month, day). Raises ValueError."""
    parts = [p for p in str(text).strip().replace("/", "-").replace(".", "-").split("-") if p]
    if len(parts) == 2:
        y, m, d = None, int(parts[0]), int(parts[1])
    elif len(parts) == 3:
        y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
    else:
        raise ValueError("use MM-DD or YYYY-MM-DD")
    date(y or 2000, m, d)  # validates (2000 is a leap year, so 02-29 is allowed)
    return y, m, d


def holidays() -> list[dict]:
    try:
        return [{**h, "kind": "holiday", "person": "", "year": None} for h in json.loads(_HOLIDAYS_FILE.read_text(encoding="utf-8"))]
    except (OSError, ValueError):
        return []


def all_events(memory) -> list[dict]:
    return holidays() + memory.events()


def _matches(e: dict, d: date) -> bool:
    if e.get("year") and e["kind"] != "birthday":
        return (e["year"], e["month"], e["day"]) == (d.year, d.month, d.day)
    return (e["month"], e["day"]) == (d.month, d.day)


def on_day(memory, d: date | None = None) -> list[dict]:
    d = d or date.today()
    out = []
    for e in all_events(memory):
        if _matches(e, d):
            e = dict(e)
            if e["kind"] == "birthday" and e.get("year"):
                e["age"] = d.year - e["year"]
            out.append(e)
    return out


def upcoming(memory, d: date | None = None, days: int = 30) -> list[dict]:
    d = d or date.today()
    out = []
    for i in range(1, days + 1):
        day = d + timedelta(days=i)
        out += [{**e, "date": day.isoformat(), "in_days": i} for e in on_day(memory, day)]
    return out


def describe(e: dict) -> str:
    who = f" ({e['person']})" if e.get("person") else ""
    age = f", turns {e['age']}" if e.get("age") else ""
    return f"{e['name']}{who} [{e['kind']}{age}]"
