"""Redact emails and phone numbers before text reaches a model provider (CLAUDE.md rule 9).

Phones are digit runs with separators and 9 to 15 digits, so dates (8 digits), ticket numbers, prices
and percentages survive. Names are not redacted (spec, risks).
"""

import re

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE = re.compile(r"(?<![\w#$])(?:\+|\()?\d[\d\s().-]{6,}\d(?![\w%])")


def _phone(match: re.Match[str]) -> str:
    digits = sum(c.isdigit() for c in match.group())
    return "[phone]" if 9 <= digits <= 15 else match.group()


def redact(text: str) -> str:
    return PHONE.sub(_phone, EMAIL.sub("[email]", text))
