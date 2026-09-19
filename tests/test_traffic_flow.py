from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from krex import (
    CongestionLevel,
    Direction,
    FlowDirection,
    KrexAuthError,
    KrexClient,
    KrexInvalidParameterError,
    KrexNotFoundError,
    KrexParseError,
    TrafficFlow,
)
from tests.test_client import FakeSession


def sample() -> dict[str, Any]:
    path = Path(__file__).parent / "fixtures/traffic-flow/live-sample.json"
    return json.loads(path.read_text(encoding="utf-8"))["response"]["body"]  # type: ignore[no-any-return]


async def test_live_fixture_semantics_and_request() -> None:
    raw = sample()
    session = FakeSession(raw)
    async with KrexClient(ex_api_key="test-key", session=session) as client:
        page = await client.traffic.flow()
    assert len(session.calls) == 1
    assert session.last_url.endswith("/openapi/odtraffic/trafficAmountByRealtime")
    assert session.last_params == {"key": "test-key", "type": "json"}
    assert page.total_count == 2
    assert page.raw == raw
    assert [item.direction for item in page] == [FlowDirection.END, FlowDirection.START]
    assert page.items[0].direction is FlowDirection.END
    assert page.items[1].direction is FlowDirection.START
    assert [item.speed for item in page] == [90, 84]
    assert [item.vds_id for item in page] == ["0010VDE00100", "0010VDS00100"]
    assert all(item.updated_at == "202609191828" for item in page)
    assert all(item.route_no == "0010" for item in page)
    assert all(item.free_flow_speed is None for item in page)
    assert all(item.congestion_level is CongestionLevel.SMOOTH for item in page)


@pytest.mark.parametrize("grade, expected", [
    ("0", None), ("1", CongestionLevel.SMOOTH),
    ("2", CongestionLevel.SLOW), ("3", CongestionLevel.STOP),
])
async def test_official_grades_and_missing_speed(grade: str, expected: Any) -> None:
    raw = sample()
    raw["list"][0].update(grade=grade, speed="-1")
    async with KrexClient(ex_api_key="test", session=FakeSession(raw)) as client:
        item = (await client.traffic.flow()).items[0]
    assert item.congestion_level is expected
    assert item.speed is None
    assert item.raw["speed"] == "-1"


@pytest.mark.parametrize("params, expected", [
    ({"route_no": "0010"}, 2),
    ({"route_no": "1"}, 0),
    ({"route_no": "9999"}, 0),
    ({"direction": FlowDirection.START}, 1),
    ({"direction": "E"}, 1),
    ({"conzone_id": "0010CZE010"}, 1),
    ({"conzone_id": "0010CZE010", "direction": FlowDirection.START}, 0),
])
async def test_local_filters(params: dict[str, Any], expected: int) -> None:
    session = FakeSession(sample())
    async with KrexClient(ex_api_key="test", session=session) as client:
        page = await client.traffic.flow(**params)
    assert len(page) == page.total_count == expected
    assert set(session.last_params) == {"key", "type"}


async def test_local_paging_preserves_vds_rows_and_raw_count() -> None:
    raw = sample()
    second_vds = copy.deepcopy(raw["list"][0])
    second_vds["vdsId"] = "another-vds"
    raw["list"].append(second_vds)
    raw["count"] = 3
    async with KrexClient(ex_api_key="test", session=FakeSession(raw)) as client:
        page = await client.traffic.flow(direction="E", num_of_rows=1, page_no=2)
        beyond = await client.traffic.flow(direction="E", num_of_rows=1, page_no=3)
    assert len(page) == 1
    assert page.first is not None and page.first.raw["vdsId"] == "another-vds"
    assert page.first.vds_id == "another-vds"
    assert page.page_no == 2 and page.num_of_rows == 1 and page.total_count == 2
    assert page.raw is not None and page.raw["count"] == 3
    assert beyond.is_empty and beyond.total_count == 2


@pytest.mark.parametrize("raw", [
    {}, {"message": "upstream failure"}, {"code": "SUCCESS"},
    {"count": 0}, {"list": []}, {"count": 1, "list": []},
    {"count": 0, "list": None}, {"count": 0, "list": ""},
    {"count": 0, "list": {}}, {"count": 1, "list": [None]},
    {"count": 1, "list": [{}]}, {"count": -1, "list": []},
    {"count": True, "list": []}, {"count": 0.0, "list": []},
    {"count": "0 rows", "list": []}, {"count": "invalid", "list": []},
    {"count": 0, "data": []},
])
@pytest.mark.parametrize("strict", [True, False])
@pytest.mark.parametrize("method", ["flow", "flow_all"])
async def test_malformed_envelopes_never_become_empty_success(
    raw: Any, strict: bool, method: str
) -> None:
    async with KrexClient(
        ex_api_key="test", strict_no_data=strict, session=FakeSession(raw)
    ) as client:
        with pytest.raises(KrexParseError):
            await getattr(client.traffic, method)()


async def test_explicit_empty_snapshot_and_single_record() -> None:
    raw = sample()
    raw["list"] = raw["list"][0]
    raw["count"] = "1"
    async with KrexClient(ex_api_key="test", session=FakeSession(raw)) as client:
        assert len(await client.traffic.flow()) == 1
    async with KrexClient(
        ex_api_key="test", session=FakeSession({"code": "SUCCESS", "count": 0, "list": []})
    ) as client:
        page = await client.traffic.flow()
    assert page.is_empty and page.total_count == 0


@pytest.mark.parametrize("changes", [
    {"conzoneId": " "}, {"speed": "broken"}, {"updownTypeCode": "X"},
    {"grade": "4"}, {"stdHour": "2500"}, {"stdHour": "12"}, {"stdHour": None},
    {"stdDate": "20260230"}, {"stdDate": None},
])
async def test_one_bad_record_rejects_whole_snapshot_before_filtering(changes: Any) -> None:
    raw = sample()
    raw["list"][0].update(changes)
    async with KrexClient(ex_api_key="test", session=FakeSession(raw)) as client:
        with pytest.raises(KrexParseError):
            await client.traffic.flow(route_no="9999")


@pytest.mark.parametrize("params", [
    {"direction": "0"}, {"direction": "1"}, {"direction": "invalid"},
    {"direction": Direction.EAST}, {"direction": Direction.UP},
    {"num_of_rows": 0}, {"page_no": -1}, {"page_no": True},
    {"num_of_rows": 1.5}, {"page_no": "1"},
    {"route_no": ""}, {"route_no": 10}, {"conzone_id": " "},
])
async def test_invalid_filters_fail_before_network(params: Any) -> None:
    session = FakeSession(sample())
    async with KrexClient(ex_api_key="test", session=session) as client:
        with pytest.raises(KrexInvalidParameterError):
            await client.traffic.flow(**params)
    assert not session.calls


async def test_provider_error_is_not_hidden_by_snapshot_validation() -> None:
    async with KrexClient(
        ex_api_key="test", session=FakeSession({"code": "INVALID_KEY", "message": "invalid"})
    ) as client:
        with pytest.raises(KrexAuthError):
            await client.traffic.flow()


async def test_zero_speed_is_not_missing_and_grade_three_means_stop() -> None:
    raw = sample()
    raw["list"][0].update(speed="0", grade="3")
    async with KrexClient(ex_api_key="test", session=FakeSession(raw)) as client:
        item = (await client.traffic.flow()).items[0]
    assert item.speed == 0
    assert item.congestion_level is CongestionLevel.STOP
    assert item.raw["grade"] == "3"


async def test_flow_all_returns_over_one_thousand_vds_rows_from_one_response() -> None:
    raw = sample()
    row = raw["list"][0]
    raw["list"] = [dict(row, vdsId=f"0010VDE{index:05}") for index in range(1002)]
    raw["count"] = 1002
    session = FakeSession(raw)
    async with KrexClient(ex_api_key="test", session=session) as client:
        page = await client.traffic.flow_all()
    assert len(session.calls) == 1
    assert session.last_params == {"key": "test", "type": "json"}
    assert len(page) == page.total_count == 1002
    assert page.page_no is None and page.num_of_rows is None
    assert len({item.conzone_id for item in page}) == 1
    assert len({item.vds_id for item in page}) == 1002
    assert [item.vds_id for item in page] == [item["vdsId"] for item in raw["list"]]
    assert page.raw == raw


async def test_flow_keeps_default_local_limit_with_one_request() -> None:
    raw = sample()
    raw["list"] = [dict(raw["list"][0], vdsId=str(index)) for index in range(1002)]
    raw["count"] = 1002
    session = FakeSession(raw)
    async with KrexClient(ex_api_key="test", session=session) as client:
        page = await client.traffic.flow()
    assert len(session.calls) == 1
    assert len(page) == page.num_of_rows == 1000
    assert page.total_count == 1002 and page.page_no == 1


async def test_flow_all_debug_and_real_fixture_vds_fields() -> None:
    raw = sample()
    async with KrexClient(ex_api_key="test", session=FakeSession(raw)) as client:
        run = await client.debug_call("traffic.flow_all")
    assert run.error is None
    assert run.request["query"]["key"] == "<REDACTED>"
    assert [item.vds_id for item in run.parsed] == ["0010VDE00100", "0010VDS00100"]
    assert all(item.vds_id == item.raw["vdsId"] for item in run.parsed)


async def test_flow_all_preserves_legacy_missing_vds_id_and_model_default() -> None:
    raw = sample()
    for item in raw["list"]:
        del item["vdsId"]
    async with KrexClient(ex_api_key="test", session=FakeSession(raw)) as client:
        page = await client.traffic.flow_all()
    assert all(item.vds_id is None for item in page)
    fields = page.items[0].model_dump(exclude={"vds_id"})
    assert TrafficFlow(**fields).vds_id is None


@pytest.mark.parametrize("strict", [True, False])
async def test_flow_all_explicit_empty_and_no_data(strict: bool) -> None:
    session = FakeSession([
        {"code": "SUCCESS", "count": 0, "list": []},
        {"code": "NO_DATA", "message": "empty"},
    ])
    async with KrexClient(ex_api_key="test", strict_no_data=strict, session=session) as client:
        page = await client.traffic.flow_all()
        assert page.is_empty and page.total_count == 0
        assert page.page_no is None and page.num_of_rows is None
        if strict:
            with pytest.raises(KrexNotFoundError):
                await client.traffic.flow_all()
        else:
            page = await client.traffic.flow_all()
            assert page.is_empty and page.total_count == 0 and page.raw is None
