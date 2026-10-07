"""The commitment check (spec F7): a drafted update must not promise what the PM didn't decide.

Dates, relative timing ("next week", "soon") and delivery promises ("we will ship") are flagged unless the PM
entered a date with the status change; with a date, only a different date is still flagged.
"""

from datetime import date

import pytest

from app.ai.commitments import check

PM_DATE = date(2026, 11, 30)


def phrases(text: str, pm_date: date | None = None) -> list[str]:
    return [f.phrase.lower() for f in check(text, pm_date)]


@pytest.mark.parametrize(
    ("text", "flagged"),
    [
        ("We will ship SSO next week.", ["we will ship", "next week"]),
        ("It should be available soon.", ["soon"]),
        ("We'll ship it by November 30.", ["we'll ship", "november 30"]),
        ("Expect it in the coming weeks, by end of quarter.", ["in the coming weeks", "end of quarter"]),
        ("Targeting 2026-12-15 for the beta.", ["2026-12-15"]),
        ("Planned for Q1.", ["q1"]),
        ("This will be released shortly.", ["will be released", "shortly"]),
        ("We promise this is coming next month.", ["we promise", "next month"]),
        ("On 15 December we launch.", ["15 december"]),
    ],
)
def test_dates_timing_and_promises_are_flagged_without_a_pm_date(text: str, flagged: list[str]) -> None:
    assert phrases(text) == flagged


def test_nothing_is_flagged_in_an_update_without_commitments() -> None:
    assert (
        phrases("Thanks for asking about SSO. We've marked it as planned; the reason is enterprise rollout.")
        == []
    )
    assert phrases("Your request was about Okta login, and it is now part of a planned need.") == []


def test_a_pm_date_allows_that_date_and_delivery_language_but_not_another_date() -> None:
    assert phrases("We will ship it by November 30.", PM_DATE) == []
    assert phrases("Targeting 2026-11-30, soon after the review.", PM_DATE) == []
    assert phrases("We will ship it by 30 Nov.", PM_DATE) == []
    assert phrases("We will ship it by December 15.", PM_DATE) == ["december 15"]


def test_flags_carry_their_position_and_kind() -> None:
    [flag] = check("Available soon.", None)
    assert (flag.kind, flag.start, flag.end) == ("timing", 10, 14)
    assert "soon" in flag.reason.lower()


@pytest.mark.parametrize(
    ("text", "flagged"),
    [
        ("We\u2019ll ship it.", ["we'll ship"]),  # a curly apostrophe, as models often write
        ("We\u2019re going to launch it.", ["we're going to launch"]),
        ("It\u2019s coming in December.", ["in december"]),
        ("Targeting December 2026.", ["december 2026"]),
        ("Expect it in two weeks.", ["in two weeks"]),
        ("Within 2 weeks, hopefully.", ["within 2 weeks"]),
        ("In a couple of weeks.", ["in a couple of weeks"]),
        ("In 1 week.", ["in 1 week"]),
        ("Ships tomorrow.", ["tomorrow"]),
        ("Ready by Friday.", ["by friday"]),
        ("Done by year-end.", ["year-end"]),
        ("Live by EOY.", ["eoy"]),
    ],
)
def test_commitments_phrased_other_ways_are_flagged(text: str, flagged: list[str]) -> None:
    assert phrases(text) == flagged


@pytest.mark.parametrize("text", ["We need 24/7 support.", "It affects 10/12 of users.", "Version 2/3 of the API.",
                                  "May we ask a question?", "Marketing loves it."])  # fmt: skip
def test_fractions_and_ordinary_words_are_not_dates(text: str) -> None:
    assert phrases(text) == []
