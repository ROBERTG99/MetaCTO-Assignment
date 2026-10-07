import pytest

from app.ai.redact import redact


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("mail carlos.mendes@atlasfreight.example now", "mail [email] now"),
        ("call +1 (415) 555-0142 today", "call [phone] today"),
        ("or 415-555-0142 or 415.555.0142", "or [phone] or [phone]"),
        ("+44 20 7946 0958", "[phone]"),
        ("We have 30 users and 2 workspaces since 2024", "We have 30 users and 2 workspaces since 2024"),
        ("SLA is 99.9% and ARR $420,000", "SLA is 99.9% and ARR $420,000"),
        ("Ticket #51877 opened 2026-10-07", "Ticket #51877 opened 2026-10-07"),
    ],
)
def test_redacts_emails_and_phones_but_not_ordinary_numbers(text: str, expected: str) -> None:
    assert redact(text) == expected
