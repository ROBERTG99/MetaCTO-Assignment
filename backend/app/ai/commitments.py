"""The commitment check (spec F7): code, not the model, decides whether a draft promises something.

A drafted stakeholder message is flagged when it names a date, a relative time ("next week", "soon", "Q1") or
a delivery promise ("we will ship", "will be released") that the PM didn't commit to. If the PM entered a date
with the status change, timing and delivery language are the PM's own commitment and pass; only a different
date is still flagged. A flagged draft can't be approved until the PM edits it (services/updates.py).
"""

import re
from dataclasses import dataclass
from datetime import date

_MONTHS = {
    m: i
    for i, names in enumerate(
        [
            ("january", "jan"),
            ("february", "feb"),
            ("march", "mar"),
            ("april", "apr"),
            ("may",),
            ("june", "jun"),
            ("july", "jul"),
            ("august", "aug"),
            ("september", "sep", "sept"),
            ("october", "oct"),
            ("november", "nov"),
            ("december", "dec"),
        ],
        start=1,
    )
    for m in names
}
_MONTH = "|".join(sorted(_MONTHS, key=len, reverse=True))
_FULL_MONTH = "january|february|march|april|may|june|july|august|september|october|november|december"
_COUNT = r"(?:a|an|one|two|three|four|five|six|a few|a couple of|\d+)"
_WEEKDAY = "monday|tuesday|wednesday|thursday|friday|saturday|sunday"

PROMISE = re.compile(
    r"\b(?:we(?:'ll| will| are going to|'re going to)\s+(?:ship|launch|release|deliver|build|have it)"
    r"|will be (?:released|available|shipped|launched|delivered|ready|live)"
    r"|we (?:promise|guarantee)|guaranteed)\b",
    re.IGNORECASE,
)
TIMING = re.compile(
    r"\b(?:next (?:week|month|quarter|year|sprint|release)|soon|shortly|any day now|tomorrow"
    r"|in the (?:coming|next few) (?:days|weeks|months)"
    rf"|(?:in|within) {_COUNT} (?:days?|weeks?|months?)"
    rf"|by (?:{_WEEKDAY})"
    r"|year-end|year end|end-of-year|eoy|eoq|eom"
    r"|(?:the )?end of (?:the )?(?:week|month|quarter|year)|this (?:week|month|quarter|year)|q[1-4](?: \d{4})?)\b",
    re.IGNORECASE,
)
DATE = re.compile(
    rf"\b(?:(?P<iso>\d{{4}}-\d{{2}}-\d{{2}})"
    rf"|(?P<md>(?:{_MONTH})\.? \d{{1,2}}(?:st|nd|rd|th)?(?:,? \d{{4}})?)"
    rf"|(?P<dm>\d{{1,2}}(?:st|nd|rd|th)? (?:{_MONTH})\.?(?: \d{{4}})?)"
    rf"|(?P<slash>\d{{1,2}}/\d{{1,2}}/\d{{2,4}})"  # only with a year: 24/7 and 10/12 of users aren't dates
    rf"|(?P<my>(?:{_FULL_MONTH}) \d{{4}})"
    rf"|(?P<mo>(?:in|by|before|until|early|mid|late) (?:{_FULL_MONTH})(?!\.? \d)))\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Flag:
    phrase: str
    kind: str  # date | timing | promise
    start: int
    end: int
    reason: str


def _parsed(m: re.Match[str]) -> tuple[int, int | None, int | None] | None:
    """(month, day or None, year or None) for a date match; None if it isn't a real date."""
    text = m.group(0).lower().replace(",", "").replace(".", "")
    try:
        if m.group("my") or m.group("mo"):
            words = text.split()
            month = next(_MONTHS[w] for w in words if w in _MONTHS)
            year = next((int(w) for w in words if w.isdigit()), None)
            return month, None, year
        if m.group("iso"):
            y, mo, d = (int(x) for x in text.split("-"))
            return mo, d, y
        if m.group("slash"):
            parts = [int(x) for x in text.split("/")]
            return parts[0], parts[1], (parts[2] if len(parts) > 2 else None)
        words = re.sub(r"(\d)(st|nd|rd|th)", r"\1", text).split()
        month = next(_MONTHS[w] for w in words if w in _MONTHS)
        nums = [int(w) for w in words if w.isdigit()]
        day = next(n for n in nums if n <= 31)
        year = next((n for n in nums if n > 31), None)
        return month, day, year
    except (StopIteration, ValueError):
        return None


def _valid(parsed: tuple[int, int | None, int | None] | None) -> bool:
    return parsed is not None and 1 <= parsed[0] <= 12 and (parsed[1] is None or 1 <= parsed[1] <= 31)


def _same_day(m: re.Match[str], pm_date: date) -> bool:
    parsed = _parsed(m)
    if parsed is None:
        return False
    month, day, year = parsed
    same_day = day is None or day == pm_date.day  # "in November" matches a PM date in November
    return month == pm_date.month and same_day and year in (None, pm_date.year)


def check(text: str, pm_date: date | None) -> list[Flag]:
    """Flags in text order. With a PM date, timing and promises pass; a date passes only if it's the PM's."""
    text = text.replace("\u2019", "'").replace("\u2018", "'")  # same length, so positions still hold
    flags: list[Flag] = []
    if pm_date is None:
        for m in PROMISE.finditer(text):
            flags.append(Flag(m.group(0), "promise", m.start(), m.end(),
                              f"“{m.group(0)}” promises delivery, but no date was set with this status change."))  # fmt: skip
        for m in TIMING.finditer(text):
            flags.append(Flag(m.group(0), "timing", m.start(), m.end(),
                              f"“{m.group(0)}” commits to a time the PM didn't set."))  # fmt: skip
    for m in DATE.finditer(text):
        if not _valid(_parsed(m)) or (pm_date is not None and _same_day(m, pm_date)):
            continue
        why = "isn't the date the PM set" if pm_date else "is a date the PM didn't set"
        flags.append(Flag(m.group(0), "date", m.start(), m.end(), f"“{m.group(0)}” {why}."))
    return sorted(flags, key=lambda f: f.start)
