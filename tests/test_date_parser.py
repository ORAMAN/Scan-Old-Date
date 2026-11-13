from datetime import date

from scan_old_date.date_parser import best_unambiguous, parse_date_candidates


def test_iso_date():
    result = parse_date_candidates("Printed 1998-07-21")
    assert result[0].value == date(1998, 7, 21)


def test_invalid_date_is_rejected():
    assert parse_date_candidates("1999-19-42") == []


def test_ambiguous_month_day_is_not_auto_selected():
    result = parse_date_candidates("03/04/98")
    assert len(result) == 2
    assert all(item.ambiguous for item in result)
    assert best_unambiguous(result) is None


def test_unambiguous_us_style_when_only_one_valid_interpretation():
    result = parse_date_candidates("13/04/98")
    assert result[0].value == date(1998, 4, 13)
