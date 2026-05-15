from __future__ import annotations

import ast
import json
from collections.abc import Mapping
from typing import Any

import streamlit as st

from krex import KexClient, get_api_catalog, get_api_catalog_item, jsonable

DEFAULT_PARAMS: dict[str, dict[str, Any]] = {
    "traffic.by_ic": {
        "ex_div_code": "00",
        "unit_code": "101",
        "in_out": "0",
        "time_unit": "1",
        "tcs_type": "2",
        "car_type": "1",
        "num_of_rows": 10,
        "page_no": 1,
    },
    "traffic.by_route": {"route_no": "0010", "time_unit": "1", "num_of_rows": 10, "page_no": 1},
    "traffic.flow": {"route_no": "0010", "num_of_rows": 10, "page_no": 1},
    "tollfee.between_tollgates": {
        "start_unit_code": "101",
        "end_unit_code": "105",
        "car_type": "1",
    },
    "restarea.route_facilities": {"num_of_rows": 10, "page_no": 1},
    "restarea.list_all": {"num_of_rows": 10, "page_no": 1},
    "restarea.weather": {"sdate": "20210507", "std_hour": 12},
    "restarea.latest_weather": {"lookback_hours": 48},
    "restarea.fuel_prices": {"num_of_rows": 10, "page_no": 1},
    "restarea.convenience_facilities": {"num_of_rows": 10, "page_no": 1},
}


def main() -> None:
    st.set_page_config(page_title="python-krex-api Debug UI", layout="wide")
    st.title("python-krex-api Debug UI")

    catalog_items = [item for item in get_api_catalog() if item.provider != "local"]
    catalog_rows = [item.model_dump(mode="json") for item in catalog_items]
    catalog_by_function = {item.function: item for item in catalog_items}

    with st.sidebar:
        st.header("API")
        function = st.selectbox(
            "API 선택",
            options=list(catalog_by_function),
            format_func=lambda value: (
                f"{value} · {catalog_by_function[value].dataset_name}"
            ),
        )
        selected = catalog_by_function[function]
        _render_service_key_link(selected.service_key_url)

        st.header("서비스키")
        st.caption("비워두면 환경변수 또는 로컬 .env의 값을 기본으로 사용합니다.")
        default_client = KexClient()
        st.caption(
            "기본키 상태: "
            f"data.ex.co.kr={'loaded' if default_client.ex_api_key else 'missing'}, "
            f"data.go.kr={'loaded' if default_client.go_api_key else 'missing'}"
        )
        ex_api_key = st.text_input("data.ex.co.kr 키", type="password")
        go_api_key = st.text_input("data.go.kr 키", type="password")

    selected_catalog = get_api_catalog_item(function)
    if selected_catalog is not None:
        st.subheader(selected_catalog.dataset_name)
        cols = st.columns(4)
        cols[0].metric("Provider", selected_catalog.provider)
        cols[1].metric("Return", selected_catalog.return_type)
        cols[2].metric("Fixture", "yes" if selected_catalog.fixture_supported else "no")
        cols[3].metric(
            "Live",
            "yes" if selected_catalog.live_verified else "no",
        )
        if selected_catalog.description:
            st.caption(selected_catalog.description)

    params_text = st.text_area(
        "파라미터(JSON 또는 Python dict)",
        value=json.dumps(DEFAULT_PARAMS.get(function, {}), ensure_ascii=False, indent=2),
        height=180,
    )

    result_tab, response_tab, trace_tab, fixture_tab, catalog_tab = st.tabs(
        ["Result", "Raw Response", "Debug Trace", "Fixture", "API Catalog"]
    )

    run = None
    if st.button("실행", type="primary"):
        try:
            params = _parse_params(params_text)
        except (SyntaxError, ValueError) as exc:
            st.error(str(exc))
        else:
            client = KexClient(
                ex_api_key=ex_api_key or None,
                go_api_key=go_api_key or None,
                retry_backoff=0,
            )
            run = client.debug_call(function, **params)
            st.session_state["last_run"] = run

    run = st.session_state.get("last_run", run)

    with result_tab:
        if run is None:
            st.info("API를 선택하고 실행하세요.")
        elif run.error:
            st.error(run.error["message"])
            st.json(run.error)
        else:
            st.json(jsonable(run.processed))

    with response_tab:
        if run is not None:
            st.json(jsonable(run.response))

    with trace_tab:
        _render_catalog_trace(function)
        if run is not None:
            st.divider()
            st.write("Trace")
            st.code("\n".join(run.trace), language="text")
            if run.catalog:
                st.write("DebugRun.catalog")
                st.dataframe([run.catalog], use_container_width=True)

    with fixture_tab:
        if run is not None:
            st.json(run.to_fixture_dict(name=f"{function}-debug"))

    with catalog_tab:
        st.dataframe(catalog_rows, use_container_width=True)


def _parse_params(value: str) -> dict[str, Any]:
    text = value.strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = ast.literal_eval(text)
    if not isinstance(parsed, Mapping):
        raise ValueError("파라미터는 object/dict 형태여야 합니다.")
    return dict(parsed)


def _render_catalog_trace(function: str) -> None:
    item = get_api_catalog_item(function)
    if item is None:
        st.warning("카탈로그 항목을 찾을 수 없습니다.")
        return

    catalog = item.model_dump(mode="json")
    st.write("Catalog")
    st.dataframe([catalog], use_container_width=True)
    st.write("데이터셋", item.dataset_name)
    if item.service_key_url:
        _render_service_key_link(item.service_key_url)


def _render_service_key_link(url: str | None) -> None:
    if not url:
        st.caption("서비스키가 필요 없는 로컬 항목입니다.")
        return
    st.link_button("서비스키 받기", url)


if __name__ == "__main__":
    main()
