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


_PATTERNS = [
    re.compile(r"(?<!\d)(20\d{2}|19\d{2})[./_\- ](\d{1,2})[./_\- ](\d{1,2})(?!\d)"),
    re.compile(r"(?<!\d)(\d{1,2})[./_\- ](\d{1,2})[./_\- ](\d{2}|\d{4})(?!\d)"),
]


def parse_date_candidates(
    text: str, min_year: int = 1950, max_year: int = 2035
) -> list[ParsedDate]:
    cleaned = text.replace("O", "0").replace("o", "0").replace("I", "1").replace("l", "1")
    found: list[ParsedDate] = []
    for match in _PATTERNS[0].finditer(cleaned):
        year, month, day = map(int, match.groups())
        _append(found, year, month, day, match.group(), 0.94, min_year, max_year)

    for match in _PATTERNS[1].finditer(cleaned):
        first, second, year_raw = match.groups()
        first, second = int(first), int(second)
        year = int(year_raw)
        if year < 100:
            year += 2000 if year <= 30 else 1900
        # If both month/day orders are valid and differ, do not silently choose.
        interpretations: list[date] = []
        for month, day in ((first, second), (second, first)):
            try:
                candidate = date(year, month, day)
            except ValueError:
                continue
            if min_year <= year <= max_year and candidate not in interpretations:
                interpretations.append(candidate)
        if len(interpretations) == 1:
            found.append(ParsedDate(interpretations[0], 0.82, match.group(), False))
        elif len(interpretations) > 1:
            found.extend(ParsedDate(item, 0.48, match.group(), True) for item in interpretations)

    unique: dict[tuple[date, str], ParsedDate] = {}
    for item in found:
        unique[(item.value, item.source_text)] = item
    return sorted(unique.values(), key=lambda item: item.confidence, reverse=True)


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
    if not items:
        return None
    if items[0].ambiguous:
        return None
    if len(items) > 1 and items[0].value != items[1].value and items[0].confidence - items[1].confidence < 0.15:
        return None
    return items[0]
