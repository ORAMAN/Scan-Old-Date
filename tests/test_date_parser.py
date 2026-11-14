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


def test_unambiguous_day_first_when_first_number_exceeds_month_range():
    result = parse_date_candidates("13/04/98")
    assert result[0].value == date(1998, 4, 13)


def test_camera_led_stamp_with_apostrophe():
    result = parse_date_candidates("7 4 '98")
    assert result
    assert result[0].value == date(1998, 7, 4)


def test_year_first_stamp_with_time_attached_to_date():
    result = parse_date_candidates("2009/08/0704:57PM")
    assert len(result) == 1
    assert result[0].value == date(2009, 8, 7)


def test_recover_slash_misread_as_seven_in_rotated_stamp():
    result = parse_date_candidates("2009706/1301:36AM")
    assert result
    assert result[0].value == date(2009, 6, 13)


def test_duplicate_ocr_reads_do_not_create_duplicate_dates():
    result = parse_date_candidates("2009-08-07 2009/08/07")
    assert len(result) == 1
    assert result[0].value == date(2009, 8, 7)


def test_vertical_camera_stamp_with_missing_final_m_in_am():
    result = parse_date_candidates("2009/06/1301:36A")
    assert result
    assert result[0].value == date(2009, 6, 13)


def test_camera_stamp_without_space_before_full_am_pm_time():
    result = parse_date_candidates("2009/08/0704:57PM")
    assert result
    assert result[0].value == date(2009, 8, 7)


def test_malformed_year_first_stamp_is_not_reinterpreted_as_day_first():
    assert parse_date_candidates("2009/05/3126AM") == []
    assert parse_date_candidates("2009/06/ 3126AM") == []
