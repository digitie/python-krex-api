"""휴게소 푸드메뉴(0502)·휴게소코드정보(0615)·휴게소 기준정보(0124).

fixture는 2026-11-27 data.ex.co.kr 실응답(공개 샘플 키)에서 몇 행만 잘라 둔 것이다.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from krex import (
    Direction,
    KrexClient,
    KrexInvalidParameterError,
    KrexParseError,
    MenuSeason,
    ServiceAreaClass,
)
from tests.test_client import FakeSession, ex_payload

FIXTURES = Path(__file__).parent / "data" / "restarea-food"


def _fixture(name: str) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return payload


async def test_food_menus_calls_0502_and_parses_real_rows() -> None:
    session = FakeSession(_fixture("0502-restBestfoodList.json"))
    client = KrexClient(ex_api_key="ex-key", retry_backoff=0, session=session)

    page = await client.restarea.food_menus(std_rest_code="000001")

    assert session.last_url.endswith("/openapi/restinfo/restBestfoodList")
    assert session.last_params["stdRestCd"] == "000001"
    assert session.last_params["numOfRows"] == 99
    assert page.total_count == 7291
    first = page.items[0]
    assert first.std_rest_code == "000001"
    assert first.rest_area_name == "서울만남(부산)휴게소"
    assert first.food_name == "농심어묵우동"
    assert first.price == 7000
    assert first.season is MenuSeason.ALL_YEAR
    assert first.is_best is False and first.is_premium is False and first.is_recommended is False
    assert first.route_code == "0010"
    assert first.menu_updated_on == date(2025, 8, 28)
    assert first.source_updated_on == date(2026, 11, 27)
    assert page.items[1].is_best is True
    # 원천은 계절 코드를 소문자로도 준다.
    assert page.items[2].raw["seasonMenu"] == "w"
    assert page.items[2].season is MenuSeason.WINTER


@pytest.mark.parametrize("change", [
    {"seasonMenu": "Q"},
    {"bestfoodyn": "?"},
    {"foodCost": "시가"},
    {"lastDtime": "not-a-date"},
    {"foodNm": ""},
])
async def test_food_menu_rejects_unknown_values_like_other_parsers(change: dict[str, str]) -> None:
    """모르는 코드·값은 결측으로 바꾸지 않는다(저장소 관례).

    한 행뿐이면 파싱 오류, 섞여 있으면 그 행만 빠진다.
    """
    good = _fixture("0502-restBestfoodList.json")["list"][0]
    bad = {**good, "seq": "999999", **change}
    session = FakeSession(ex_payload([bad]))
    client = KrexClient(ex_api_key="ex-key", retry_backoff=0, session=session)
    with pytest.raises(KrexParseError):
        await client.restarea.food_menus()

    session = FakeSession(ex_payload([good, bad]))
    client = KrexClient(ex_api_key="ex-key", retry_backoff=0, session=session)
    page = await client.restarea.food_menus()
    assert [menu.seq for menu in page.items] == [good["seq"]]


@pytest.mark.parametrize("call", ["food_menus", "locations"])
async def test_num_of_rows_above_the_server_cap_is_rejected(call: str) -> None:
    session = FakeSession(ex_payload([]))
    client = KrexClient(ex_api_key="ex-key", retry_backoff=0, session=session)
    with pytest.raises(KrexInvalidParameterError):
        await getattr(client.restarea, call)(num_of_rows=100)
    assert session.calls == []


async def test_service_area_codes_calls_0615_and_parses_class_and_direction() -> None:
    session = FakeSession(_fixture("0615-hiwaySvarInfoList.json"))
    client = KrexClient(ex_api_key="ex-key", retry_backoff=0, session=session)

    page = await client.restarea.service_area_codes(std_rest_code=None, route_code="7001")

    assert session.last_url.endswith("/openapi/restinfo/hiwaySvarInfoList")
    assert session.last_params["routeCd"] == "7001"
    assert "numOfRows" not in session.last_params
    station, rest = page.items[0], page.items[1]
    assert station.name == "김제(새만금)주유소"
    assert station.facility_class is ServiceAreaClass.GAS_STATION
    assert station.service_area_code == "B00249"
    assert station.std_rest_code == "000616"
    assert rest.std_rest_code == "000614"
    assert rest.service_area_code == "A00320"
    assert rest.head_office_code == "800000" and rest.branch_office_code == "810100"
    assert rest.facility_class is ServiceAreaClass.REST_AREA
    assert rest.direction is Direction.DOWN
    assert rest.direction.label == "하행"
    assert page.items[2].direction is Direction.UP
    assert rest.route_code == "7001"
    assert rest.route_name is None


async def test_locations_calls_0124_and_keeps_leading_zero_codes() -> None:
    session = FakeSession(_fixture("0124-locationinfoRest.json"))
    client = KrexClient(ex_api_key="ex-key", retry_backoff=0, session=session)

    page = await client.restarea.locations(route_no="0010")

    assert session.last_url.endswith("/openapi/locationinfo/locationinfoRest")
    assert session.last_params["routeNo"] == "0010"
    first = page.items[0]
    assert first.unit_code == "001"
    assert first.std_rest_code == "000001"
    assert first.service_area_code == "A00001"
    assert first.lon == 127.042514 and first.lat == 37.459939


async def test_location_outside_korea_becomes_none() -> None:
    row = {"unitCode": "009", "unitName": "x", "xValue": "0", "yValue": "0"}
    session = FakeSession(ex_payload([row]))
    client = KrexClient(ex_api_key="ex-key", retry_backoff=0, session=session)

    location = (await client.restarea.locations()).items[0]

    assert location.lat is None and location.lon is None
