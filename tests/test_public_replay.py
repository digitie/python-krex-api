"""휴게소 기상 단일행 재해석은 기존 client parser를 공유한다."""

from copy import deepcopy
from datetime import timedelta

import pytest

from krex import KrexClient, parse_rest_area_weather
from tests.test_client import FakeSession, ex_payload, rest_weather_row


async def test_replay_equals_http_dto_without_network_or_input_mutation() -> None:
    raw = rest_weather_row(providerExtra={"unknown": "original"})
    before = deepcopy(raw)
    session = FakeSession(ex_payload([raw]))
    client = KrexClient(ex_api_key="fixture-key", retry_backoff=0, session=session)
    original = (await client.restarea.weather(sdate="20210507", std_hour=12)).items[0]
    count = len(session.calls)
    replay = parse_rest_area_weather(raw)
    assert replay == original and replay.raw == before and raw == before
    assert replay.unit_code == "002" and replay.route_no == "0010"
    assert replay.observed_at.utcoffset() == timedelta(hours=9)
    assert len(session.calls) == count


def test_existing_sentinel_and_coordinate_semantics_are_preserved() -> None:
    replay = parse_rest_area_weather(rest_weather_row(
        tempValue="-99.0", xValue="-99.0", yValue="-99.0",
    ))
    assert replay.temperature is None and replay.latitude is None and replay.longitude is None
    assert replay.raw["tempValue"] == "-99.0"


@pytest.mark.parametrize("changes", [{"unitCode": ""}, {"sdate": "20260230"}, {"stdHour": "24"}])
def test_invalid_required_source_value_keeps_existing_value_error(changes) -> None:
    with pytest.raises(ValueError):
        parse_rest_area_weather(rest_weather_row(**changes))
