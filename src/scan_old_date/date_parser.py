from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, time
from typing import Iterable


@dataclass(frozen=True)
class ParsedDate:
    value: date
    confidence: float
    source_text: str
    ambiguous: bool = False
    captured_time: time | None = None


# Camera stamps commonly attach the time directly to the date, e.g. 2009/08/0704:57PM.
_TIME_SUFFIX = (
    r"(?:\s*(?P<hour>\d{1,2})[:.](?P<minute>\d{2})"
    r"(?:[:.](?P<second>\d{2}))?\s*(?P<ampm>[AP]M?)?)?"
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
    r"(?<!\d)(\d{1,2})(?!\d)[ ./_-]+(\d{1,2})(?!\d)"
    r"\s*['’]?\s*(\d{2})" + _TIME_SUFFIX + r"(?!\d)",
    re.IGNORECASE,
)


def _parse_captured_time(match: re.Match[str]) -> time | None:
    hour_raw = match.groupdict().get("hour")
    if hour_raw is None:
        return None

    hour = int(hour_raw)
    minute = int(match.groupdict().get("minute") or 0)
    second = int(match.groupdict().get("second") or 0)
    ampm = (match.groupdict().get("ampm") or "").upper()

    if ampm:
        if not 1 <= hour <= 12:
            return None
        if ampm.startswith("P") and hour != 12:
            hour += 12
        elif ampm.startswith("A") and hour == 12:
            hour = 0
    elif not 0 <= hour <= 23:
        return None

    try:
        return time(hour, minute, second)
    except ValueError:
        return None


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
        _append(
            found, year, month, day, match.group(), 0.96, min_year, max_year,
            _parse_captured_time(match),
        )

    for match in _OCR_YEAR_FIRST.finditer(cleaned):
        year, month, day = map(int, match.groups()[:3])
        _append(
            found, year, month, day, match.group(), 0.78, min_year, max_year,
            _parse_captured_time(match),
        )

    # Avoid parsing the month/day portion of a year-first stamp as a compact LED date.
    led_spans: set[tuple[int, int]] = set()
    for match in _LED_STAMP.finditer(cleaned):
        prefix = cleaned[: match.start()]
        if (
            re.search(r"(?<!\d)(?:19|20)\d{2}[./_-]\s*$", prefix)
            or re.search(
                r"(?<!\d)(?:19|20)\d{2}[./_-]\d{1,2}[./_-]\d{1,2}\s*$",
                prefix,
            )
        ):
            continue
        first, second, year_raw = map(int, match.groups()[:3])
        year = _expand_year(year_raw)
        led_spans.add(match.span())
        _add_month_day_interpretations(
            found, first, second, year, match.group(), 0.78, min_year, max_year,
            _parse_captured_time(match),
        )

    for match in _DAY_FIRST.finditer(cleaned):
        if any(start <= match.start() and match.end() <= end for start, end in led_spans):
            continue
        # Do not reinterpret month/day digits inside a damaged year-first stamp
        # as an unrelated day-first date (e.g. 2009/05/3126AM -> 2026-05-31).
        prefix = cleaned[: match.start()]
        if (
            re.search(r"(?<!\d)(?:19|20)\d{2}[./_-]\s*$", prefix)
            or re.search(
                r"(?<!\d)(?:19|20)\d{2}[./_-]\d{1,2}[./_-]\d{1,2}\s*$",
                prefix,
            )
        ):
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
            _parse_captured_time(match),
        )

    # Keep the strongest interpretation of each date/time pair. A read with a time
    # must not be discarded merely because another OCR pass returned only the date.
    unique: dict[tuple[date, time | None], ParsedDate] = {}
    for item in found:
        key = (item.value, item.captured_time)
        current = unique.get(key)
        if current is None or item.confidence > current.confidence:
            unique[key] = item
    return sorted(
        unique.values(),
        key=lambda item: (
            item.confidence,
            item.captured_time is not None,
            not item.ambiguous,
        ),
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
    captured_time: time | None = None,
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
        output.append(
            ParsedDate(interpretations[0], confidence, source, False, captured_time)
        )
    elif len(interpretations) > 1:
        output.extend(
            ParsedDate(item, min(0.50, confidence), source, True, captured_time)
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
    captured_time: time | None = None,
) -> None:
    if not min_year <= year <= max_year:
        return
    try:
        output.append(
            ParsedDate(date(year, month, day), confidence, source, False, captured_time)
        )
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
