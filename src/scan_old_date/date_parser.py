from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Iterable


@dataclass(frozen=True)
class ParsedDate:
    value: date
    confidence: float
    source_text: str
    ambiguous: bool = False


# Some camera stamps have the time printed immediately after the date, with no space.
_TIME_SUFFIX = (
    r"(?:\s*\d{1,2}[:.]\d{2}(?:[:.]\d{2})?"
    r"(?:\s*[AP]M?)?)?"
)
_YEAR_FIRST = re.compile(
    rf"(?<!\d)(20\d{{2}}|19\d{{2}})[./_\- ](\d{{1,2}})[./_\- ](\d{{1,2}}){_TIME_SUFFIX}(?!\d)",
    re.IGNORECASE,
)
# In small/rotated stamps, Tesseract sometimes reads the slash after the year as 7 or 1:
# 2009/06/13 -> 2009706/13. Accept only a valid 2-digit month/day in this pattern.
_OCR_YEAR_FIRST = re.compile(
    rf"(?<!\d)(20\d{{2}}|19\d{{2}})[71](0[1-9]|1[0-2])[./_\-](0[1-9]|[12]\d|3[01]){_TIME_SUFFIX}(?!\d)",
    re.IGNORECASE,
)
_DAY_FIRST = re.compile(
    rf"(?<!\d)(\d{{1,2}})[./_\- ](\d{{1,2}})[./_\- ](\d{{2}}|\d{{4}}){_TIME_SUFFIX}(?!\d)",
    re.IGNORECASE,
)
# Common compact LED camera stamp: M D 'YY, M-D-YY or M D YY.
_LED_STAMP = re.compile(
    r"(?<!\d)(\d{1,2})[ ./_-]+(\d{1,2})\s*['’]?\s*(\d{2})(?!\d)"
)


def parse_date_candidates(
    text: str, min_year: int = 1950, max_year: int = 2035
) -> list[ParsedDate]:
    cleaned = (
        text.replace("O", "0")
        .replace("o", "0")
        .replace("I", "1")
        .replace("l", "1")
    )
    found: list[ParsedDate] = []

    for match in _YEAR_FIRST.finditer(cleaned):
        year, month, day = map(int, match.groups()[:3])
        _append(found, year, month, day, match.group(), 0.96, min_year, max_year)

    for match in _OCR_YEAR_FIRST.finditer(cleaned):
        year, month, day = map(int, match.groups()[:3])
        _append(found, year, month, day, match.group(), 0.78, min_year, max_year)

    # Avoid parsing the same substring twice as both a generic and LED pattern.
    led_spans: set[tuple[int, int]] = set()
    for match in _LED_STAMP.finditer(cleaned):
        first, second, year_raw = map(int, match.groups())
        year = _expand_year(year_raw)
        led_spans.add(match.span())
        _add_month_day_interpretations(
            found, first, second, year, match.group(), 0.78, min_year, max_year
        )

    for match in _DAY_FIRST.finditer(cleaned):
        if any(start <= match.start() and match.end() <= end for start, end in led_spans):
            continue
        # Do not reinterpret month/day digits inside a damaged year-first stamp
        # as an unrelated day-first date (e.g. 2009/05/3126AM -> 2026-05-31).
        prefix = cleaned[: match.start()]
        if re.search(r"(?<!\\d)(?:19|20)\\d{2}[./_-]\\s*$", prefix):
            continue
        first, second, year_raw = match.groups()[:3]
        _add_month_day_interpretations(
            found,
            int(first),
            int(second),
            _expand_year(int(year_raw)),
            match.group(),
            0.82,
            min_year,
            max_year,
        )

    # Keep the strongest interpretation of each actual calendar date. Different
    # OCR passes often return the same date with slightly different surrounding text.
    unique: dict[date, ParsedDate] = {}
    for item in found:
        current = unique.get(item.value)
        if current is None or item.confidence > current.confidence:
            unique[item.value] = item
    return sorted(
        unique.values(),
        key=lambda item: (item.confidence, not item.ambiguous),
        reverse=True,
    )


def _expand_year(year: int) -> int:
    if year < 100:
        return year + (2000 if year <= 30 else 1900)
    return year


def _add_month_day_interpretations(
    output: list[ParsedDate],
    first: int,
    second: int,
    year: int,
    source: str,
    confidence: float,
    min_year: int,
    max_year: int,
) -> None:
    if not min_year <= year <= max_year:
        return
    interpretations: list[date] = []
    for month, day in ((first, second), (second, first)):
        try:
            candidate = date(year, month, day)
        except ValueError:
            continue
        if candidate not in interpretations:
            interpretations.append(candidate)
    if len(interpretations) == 1:
        output.append(ParsedDate(interpretations[0], confidence, source, False))
    elif len(interpretations) > 1:
        output.extend(
            ParsedDate(item, min(0.50, confidence), source, True)
            for item in interpretations
        )


def _append(
    output: list[ParsedDate],
    year: int,
    month: int,
    day: int,
    source: str,
    confidence: float,
    min_year: int,
    max_year: int,
) -> None:
    if not min_year <= year <= max_year:
        return
    try:
        output.append(ParsedDate(date(year, month, day), confidence, source, False))
    except ValueError:
        return


def best_unambiguous(candidates: Iterable[ParsedDate]) -> ParsedDate | None:
    items = list(candidates)
    if not items or items[0].ambiguous:
        return None
    if (
        len(items) > 1
        and items[0].value != items[1].value
        and items[0].confidence - items[1].confidence < 0.15
    ):
        return None
    return items[0]
