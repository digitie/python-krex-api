from datetime import date, datetime

import pytest

from krex._convert import (
    normalize_items,
    parse_datetime_text,
    strip_or_none,
    to_bool_yn,
    to_date_or_none,
    to_float_or_none,
    to_int_or_none,
)


def test_scalar_conversions_match_public_api_strings() -> None:
    assert strip_or_none("  ") is None
    assert to_int_or_none("1,234") == 1234
    assert to_int_or_none("1,994원") == 1994
    assert to_float_or_none("+12.5") == 12.5
    assert to_float_or_none("87.5km/h") == 87.5
    assert to_date_or_none("20260430") == date(2026, 4, 30)
    assert to_date_or_none("2026-04-30") == date(2026, 4, 30)
    assert to_bool_yn("Y") is True
    assert to_bool_yn("n") is False
    assert to_bool_yn("O") is True
    assert to_bool_yn("X") is False


def test_bool_rejects_unknown_text() -> None:
    with pytest.raises(ValueError):
        to_bool_yn("maybe")


def test_normalize_items_accepts_single_dict_and_list() -> None:
    assert normalize_items({"a": 1}, "item") == [{"a": 1}]
    assert normalize_items([{"a": 1}, {"b": 2}], "item") == [{"a": 1}, {"b": 2}]
    assert normalize_items(None, "item") == []


def test_normalize_items_rejects_bad_shapes() -> None:
    with pytest.raises(TypeError):
        normalize_items(["bad"], "item")


def test_parse_datetime_text_accepts_common_shapes() -> None:
    assert parse_datetime_text("202604301230") == datetime(2026, 4, 30, 12, 30)
    assert parse_datetime_text("2026-04-30T12:30:45") == datetime(2026, 4, 30, 12, 30, 45)
    assert parse_datetime_text("not-a-date") is None
