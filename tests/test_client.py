from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from kex_openapi import (
    CarType,
    CongestionLevel,
    CoordinateSystem,
    Direction,
    KexClient,
    KexInvalidParameterError,
    KexNotFoundError,
    KexParseError,
    RoadOperator,
    TCSType,
    TimeUnit,
)


class FakeResponse:
    def __init__(self, payload: dict[str, Any], status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self) -> dict[str, Any]:
        return self._payload


class FakeSession:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.calls: list[dict[str, Any]] = []

    @property
    def last_params(self) -> dict[str, Any]:
        return self.calls[-1]["params"]

    @property
    def last_url(self) -> str:
        return self.calls[-1]["url"]

    def get(self, url: str, *, params: dict[str, Any], timeout: float) -> FakeResponse:
        self.calls.append({"url": url, "params": params, "timeout": timeout})
        return FakeResponse(self.payload)


def ex_payload(items: Any) -> dict[str, Any]:
    return {"code": "SUCCESS", "pageNo": "1", "numOfRows": "1000", "count": "1", "list": items}


def go_payload(items: Any) -> dict[str, Any]:
    return {
        "response": {
            "header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE"},
            "body": {"items": {"item": items}, "pageNo": "1", "numOfRows": "10", "totalCount": "1"},
        }
    }


def test_traffic_by_ic_builds_query_and_parses_types() -> None:
    session = FakeSession(
        ex_payload(
            [
                {
                    "stdDate": "20260430",
                    "stdTime": "1400",
                    "unitCode": "101",
                    "unitName": "서울",
                    "inoutType": "0",
                    "tcsType": "2",
                    "carType": "1",
                    "trafficAmout": "1,234",
                    "sumTm": "1400",
                    "sumDate": "20260430",
                }
            ]
        )
    )
    client = KexClient(ex_api_key="ex-key", retry_backoff=0, session=session)

    page = client.traffic.by_ic(
        ex_div_code=RoadOperator.KEC,
        unit_code="101",
        in_out="0",
        time_unit=TimeUnit.HOUR,
        tcs_type=TCSType.HIPASS,
        car_type=CarType.LIGHT,
    )

    assert session.last_url.endswith("/openapi/trafficapi/trafficIc")
    assert session.last_params["exDivCode"] == "00"
    assert session.last_params["inOutType"] == "0"
    assert session.last_params["tmType"] == "1"
    assert session.last_params["tcsType"] == "2"
    assert page.total_count == 1
    item = page.items[0]
    assert item.collected_date == date(2026, 4, 30)
    assert item.in_out is not None
    assert item.tcs_type is TCSType.HIPASS
    assert item.car_type is CarType.LIGHT
    assert item.traffic_volume == 1234


def test_traffic_flow_accepts_single_dict_response() -> None:
    session = FakeSession(
        ex_payload(
            {
                "conzoneId": "0010CZE010",
                "conzoneName": "서울-수원",
                "routeNo": "0010",
                "routeName": "경부고속도로",
                "dirType": "0",
                "speed": "87.5",
                "tmFreeFlow": "100",
                "congestionLevel": "1",
                "updTime": "202604301405",
            }
        )
    )
    client = KexClient(ex_api_key="ex-key", retry_backoff=0, session=session)

    page = client.traffic.flow(route_no="0010", direction=Direction.UP)

    assert session.last_params["routeNo"] == "0010"
    assert session.last_params["dirType"] == "0"
    flow = page.items[0]
    assert flow.congestion_level is CongestionLevel.SMOOTH
    assert flow.speed == pytest.approx(87.5)
    assert flow.free_flow_speed == pytest.approx(100.0)


def test_tollfee_between_tollgates_parses_money_and_distance() -> None:
    session = FakeSession(
        ex_payload(
            [
                {
                    "startUnitCode": "101",
                    "startUnitName": "서울",
                    "endUnitCode": "105",
                    "endUnitName": "수원",
                    "carType": "1",
                    "discountType": "0",
                    "routeCount": "1",
                    "totalLength": "31.2",
                    "travelTime": "28",
                    "tollFee": "2,300",
                    "tollFeeNight": "1,800",
                    "tollFeeRush": "2,100",
                }
            ]
        )
    )
    client = KexClient(ex_api_key="ex-key", retry_backoff=0, session=session)

    page = client.tollfee.between_tollgates(
        start_unit_code="101",
        end_unit_code="105",
        car_type="1",
    )

    assert session.last_params["startUnitCode"] == "101"
    assert session.last_params["endUnitCode"] == "105"
    assert page.items[0].total_length_km == pytest.approx(31.2)
    assert page.items[0].toll_fee == 2300


def test_tollgate_list_preserves_code_strings() -> None:
    session = FakeSession(
        ex_payload(
            [
                {
                    "unitCode": "007",
                    "unitName": "테스트TG",
                    "routeNo": "0010",
                    "routeName": "경부고속도로",
                    "xValue": "127.1",
                    "yValue": "37.2",
                }
            ]
        )
    )
    client = KexClient(ex_api_key="ex-key", retry_backoff=0, session=session)

    tollgate = client.tollfee.tollgate_list().items[0]

    assert tollgate.unit_code == "007"
    assert tollgate.x == pytest.approx(127.1)
    assert tollgate.coordinate is not None
    assert tollgate.coordinate.lonlat == pytest.approx((127.1, 37.2))
    assert tollgate.raw_coordinate is not None
    assert tollgate.raw_coordinate.system is CoordinateSystem.WGS84


def test_restarea_standard_data_uses_go_key_and_parses_bool() -> None:
    session = FakeSession(
        go_payload(
            [
                {
                    "restAreaNm": "죽전휴게소",
                    "routeNm": "경부고속도로",
                    "directionContent": "서울방향",
                    "lcLatitude": "37.332",
                    "lcLongitude": "127.104",
                    "gasStnYn": "Y",
                    "lpgStnYn": "N",
                    "evChargYn": "Y",
                    "phoneNumber": "031-000-0000",
                    "referenceDate": "2026-04-30",
                }
            ]
        )
    )
    client = KexClient(go_api_key="go-key", retry_backoff=0, session=session)

    rest_area = client.restarea.list_all(route_name="경부고속도로").items[0]

    assert session.last_url == "https://api.data.go.kr/openapi/tn_pubr_public_rest_area_api"
    assert session.last_params["serviceKey"] == "go-key"
    assert session.last_params["type"] == "json"
    assert "_type" not in session.last_params
    assert rest_area.name == "죽전휴게소"
    assert rest_area.has_gas_station is True
    assert rest_area.has_lpg_station is False
    assert rest_area.reference_date == date(2026, 4, 30)
    assert rest_area.coordinate is not None
    assert rest_area.coordinate.lonlat == pytest.approx((127.104, 37.332))


def test_food_price_parses_recommend_flag() -> None:
    session = FakeSession(
        ex_payload(
            {
                "serviceAreaCode": "A001",
                "serviceAreaName": "죽전",
                "storeName": "푸드코트",
                "foodName": "우동",
                "price": "7,000",
                "recommendYn": "Y",
            }
        )
    )
    client = KexClient(ex_api_key="ex-key", retry_backoff=0, session=session)

    food = client.restarea.food_price().items[0]

    assert food.food_name == "우동"
    assert food.price == 7000
    assert food.is_recommended is True


def test_no_data_can_return_empty_page_when_configured() -> None:
    session = FakeSession({"code": "NO_DATA", "message": "empty"})
    client = KexClient(ex_api_key="ex-key", retry_backoff=0, strict_no_data=False, session=session)

    page = client.traffic.flow(route_no="9999")

    assert page.items == ()


def test_no_data_raises_by_default() -> None:
    session = FakeSession({"code": "NO_DATA", "message": "empty"})
    client = KexClient(ex_api_key="ex-key", retry_backoff=0, session=session)

    with pytest.raises(KexNotFoundError):
        client.traffic.flow(route_no="9999")


def test_invalid_public_params_fail_before_http_call() -> None:
    session = FakeSession(ex_payload([]))
    client = KexClient(ex_api_key="ex-key", retry_backoff=0, session=session)

    with pytest.raises(KexInvalidParameterError):
        client.tollfee.between_tollgates(start_unit_code="", end_unit_code="105", car_type="1")
    with pytest.raises(KexInvalidParameterError):
        client.traffic.by_ic(
            ex_div_code="00",
            unit_code="101",
            in_out="0",
            time_unit="9",
            tcs_type="2",
            car_type="1",
        )
    assert session.calls == []


def test_malformed_model_record_raises_parse_error() -> None:
    session = FakeSession(ex_payload([{"unitName": "missing unit code"}]))
    client = KexClient(ex_api_key="ex-key", retry_backoff=0, session=session)

    with pytest.raises(KexParseError):
        client.tollfee.tollgate_list()


def test_reference_codes_are_local_and_preserve_leading_zero_routes() -> None:
    client = KexClient(ex_api_key="unused")

    routes = client.reference.routes()
    codes = client.reference.common_codes()

    assert routes[0].route_no == "0010"
    assert codes["car_type"]["1"] == "1종"


def test_raw_and_generic_namespaces_build_expected_urls() -> None:
    session = FakeSession(ex_payload([{"any": "value"}]))
    client = KexClient(ex_api_key="ex-key", go_api_key="go-key", retry_backoff=0, session=session)

    assert client.traffic.by_route(route_no="0010", time_unit="1").items[0] == {"any": "value"}
    assert session.last_url.endswith("/openapi/trafficapi/trafficRoute")

    client.traffic.vds_raw(vdsId="V001")
    assert session.last_url.endswith("/openapi/trafficapi/vdsRaw")

    client.traffic.avc_raw(vds_id="V001", std_date="20260430")
    assert session.last_params["vdsId"] == "V001"
    assert session.last_url.endswith("/openapi/trafficapi/avcRaw")

    client.restarea.parking(serviceAreaName="죽전")
    assert session.last_url.endswith("/openapi/restinfo/restParking")

    client.restarea.wifi()
    assert session.last_url.endswith("/openapi/restinfo/restWifi")

    client.restarea.restroom()
    assert session.last_url.endswith("/openapi/restinfo/restRestroom")

    client.facility.drowsy_shelter()
    assert session.last_url.endswith("/openapi/restinfo/drowsyShelter")


def test_data_go_generic_namespaces_build_expected_urls() -> None:
    session = FakeSession(go_payload([{"any": "value"}]))
    client = KexClient(go_api_key="go-key", retry_backoff=0, session=session)

    client.facility.tollgate_info()
    assert session.last_url.endswith("/TollgateInfoService/getTollgateInfo")
    assert session.last_params["_type"] == "json"

    client.facility.shoulder_lane()
    assert session.last_url.endswith("/ShoulderLaneService/getShoulderLane")

    client.admin.procurement_contracts()
    assert session.last_url.endswith("/ProcurementContractService/getContracts")
