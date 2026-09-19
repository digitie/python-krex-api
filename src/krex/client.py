"""한국도로공사 OpenAPI 고수준 클라이언트."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, TypeVar, cast

from ._convert import (
    strip_or_none,
    to_bool_yn,
    to_date_or_none,
    to_float_or_none,
    to_int_or_none,
)
from ._env import get_local_env_value
from ._http import DEFAULT_MAX_RPS, KrexHttp, NormalizedPayload, normalize_api_key
from ._ratelimit import AsyncTokenBucket
from .catalog import get_api_catalog, get_api_catalog_item
from .codes import (
    ROUTE_NAMES,
    CarType,
    CongestionLevel,
    CoordinateSystem,
    Direction,
    DiscountType,
    FlowDirection,
    IOType,
    KrexCode,
    RoadOperator,
    TCSType,
    TimeUnit,
    coerce_code,
)
from .debug import DebugRun, exception_to_debug_error, jsonable, safe_debug_value
from .exceptions import KrexError, KrexInvalidParameterError, KrexNotFoundError, KrexParseError
from .models import (
    ApiCatalogItem,
    FoodPrice,
    Incident,
    Page,
    RawCoordinate,
    RestArea,
    RestAreaFuelPrice,
    RestAreaRouteFacility,
    RestAreaWeather,
    Route,
    TollFee,
    Tollgate,
    TrafficByIc,
    TrafficFlow,
)

T = TypeVar("T")
E = TypeVar("E", bound=KrexCode)
KST = timezone(timedelta(hours=9), "KST")
_MAX_LATEST_WEATHER_LOOKBACK_HOURS = 240


class KrexClient:
    """Krex OpenAPI 호출 진입점.

    엔드포인트 문서(`endpoints.md`)와 메서드 이름이 비슷하게 보이도록
    `traffic`, `tollfee`, `restarea`, `facility`, `admin`, `reference`
    네임스페이스를 제공합니다.
    """

    def __init__(
        self,
        ex_api_key: str | None = None,
        go_api_key: str | None = None,
        *,
        timeout: float = 10.0,
        strict_no_data: bool = True,
        max_retries: int = 2,
        retry_backoff: float = 0.5,
        session: Any | None = None,
        max_rps: float = DEFAULT_MAX_RPS,
        rate_limiter: AsyncTokenBucket | None = None,
    ) -> None:
        self.ex_api_key = normalize_api_key(ex_api_key) or normalize_api_key(
            get_local_env_value("KEX_EX_API_KEY")
        )
        self.go_api_key = normalize_api_key(go_api_key) or normalize_api_key(
            get_local_env_value("DATA_GO_KR_SERVICE_KEY")
        )
        self.strict_no_data = strict_no_data
        self.rate_limiter = (
            rate_limiter if rate_limiter is not None else AsyncTokenBucket(max_rps, capacity=1)
        )
        self._http = KrexHttp(
            self.ex_api_key,
            self.go_api_key,
            timeout=timeout,
            max_retries=max_retries,
            retry_backoff=retry_backoff,
            session=session,
            rate_limiter=self.rate_limiter,
            max_rps=max_rps,
        )
        self.traffic = TrafficService(self)
        self.tollfee = TollfeeService(self)
        self.restarea = RestareaService(self)
        self.facility = FacilityService(self)
        self.admin = AdminService(self)
        self.reference = ReferenceService(self)
        self.closed = False

    @classmethod
    def from_env(cls, **kwargs: Any) -> KrexClient:
        return cls(**kwargs)

    async def debug_call(self, function: str, **params: Any) -> DebugRun:
        """외부 Debug UI가 사용할 수 있는 단일 함수 실행 정보를 반환합니다."""

        trace = [f"resolve {function}"]
        catalog_item = get_api_catalog_item(function)
        catalog = jsonable(catalog_item) if catalog_item is not None else None
        if catalog_item is not None:
            trace.append(f"catalog dataset: {catalog_item.dataset_name}")
            if catalog_item.service_key_url:
                trace.append(f"service key URL: {catalog_item.service_key_url}")
        parsed: Any = None
        processed: Any = None
        error: dict[str, Any] | None = None
        secrets = (self.ex_api_key, self.go_api_key)
        with self._http.capture_calls():
            self._http.last_request = None
            self._http.last_response = None
            try:
                method = self._resolve_debug_function(function)
                trace.append("call public client method")
                value = method(**params)
                parsed = await value if inspect.isawaitable(value) else value
                processed = parsed
                trace.append("call completed")
            except Exception as exc:  # noqa: BLE001 - 디버그 UI는 예외를 화면에 보여줘야 합니다.
                error = exception_to_debug_error(exc)
                trace.append(f"error: {type(exc).__name__}")
            return DebugRun(
                function=function,
                input=safe_debug_value(dict(params), secrets),
                request=safe_debug_value(self._http.last_request or {}, secrets),
                response=safe_debug_value(self._http.last_response or {}, secrets),
                parsed=safe_debug_value(parsed, secrets),
                processed=safe_debug_value(processed, secrets),
                trace=trace,
                catalog=catalog,
                error=safe_debug_value(error, secrets),
            )

    def _resolve_debug_function(self, function: str) -> Callable[..., Any]:
        parts = function.split(".")
        if len(parts) != 2 or any(part.startswith("_") or not part for part in parts):
            raise KrexInvalidParameterError("function must look like 'namespace.method'")
        if get_api_catalog_item(function) is None:
            raise KrexInvalidParameterError(f"unknown debug function: {function}")
        namespace = getattr(self, parts[0], None)
        method = getattr(namespace, parts[1], None)
        if not callable(method):
            raise KrexInvalidParameterError(f"unknown debug function: {function}")
        return cast(Callable[..., Any], method)

    async def aclose(self) -> None:
        await self._http.aclose()
        self.closed = True

    async def __aenter__(self) -> KrexClient:
        return self

    async def __aexit__(self, *_exc_info: Any) -> None:
        await self.aclose()

    async def _page_ex(
        self,
        path: str,
        params: dict[str, Any],
        parser: Callable[[dict[str, Any]], T],
    ) -> Page[T]:
        try:
            try:
                payload = await self._http.get_ex(path, _clean(params))
            except KrexNotFoundError:
                if self.strict_no_data:
                    raise
                return Page(items=())
            return _parse_page(payload, parser)
        except KrexError as exc:
            self._http.protect_error(exc)
            raise exc from None

    async def _page_go(
        self,
        url: str,
        params: dict[str, Any],
        parser: Callable[[dict[str, Any]], T],
        *,
        standard: bool = False,
    ) -> Page[T]:
        try:
            try:
                payload = await self._http.get_go(url, _clean(params), standard=standard)
            except KrexNotFoundError:
                if self.strict_no_data:
                    raise
                return Page(items=())
            return _parse_page(payload, parser)
        except KrexError as exc:
            self._http.protect_error(exc)
            raise exc from None


@dataclass(frozen=True, slots=True)
class TrafficService:
    _client: KrexClient

    async def by_ic(
        self,
        *,
        ex_div_code: RoadOperator | str,
        unit_code: str,
        in_out: IOType | str,
        time_unit: TimeUnit | str,
        tcs_type: TCSType | str,
        car_type: CarType | str,
        num_of_rows: int = 1000,
        page_no: int = 1,
    ) -> Page[TrafficByIc]:
        try:
            _require(unit_code, "unit_code")
            return await self._client._page_ex(
                "/openapi/trafficapi/trafficIc",
                {
                    "exDivCode": coerce_code(RoadOperator, ex_div_code, "ex_div_code"),
                    "unitCode": unit_code,
                    "inOutType": coerce_code(IOType, in_out, "in_out"),
                    "tmType": coerce_code(TimeUnit, time_unit, "time_unit"),
                    "tcsType": coerce_code(TCSType, tcs_type, "tcs_type"),
                    "carType": coerce_code(CarType, car_type, "car_type"),
                    "numOfRows": num_of_rows,
                    "pageNo": page_no,
                },
                _traffic_by_ic,
            )
        except KrexError as exc:
            self._client._http.protect_error(exc)
            raise exc from None

    async def by_route(
        self,
        *,
        route_no: str,
        time_unit: TimeUnit | str,
        direction: Direction | str | None = None,
        car_type: CarType | str | None = None,
        std_date: str | None = None,
        num_of_rows: int = 1000,
        page_no: int = 1,
    ) -> Page[dict[str, Any]]:
        try:
            _require(route_no, "route_no")
            return await self._client._page_ex(
                "/openapi/trafficapi/trafficRoute",
                {
                    "routeNo": route_no,
                    "tmType": coerce_code(TimeUnit, time_unit, "time_unit"),
                    "dirType": _optional_code(Direction, direction, "direction"),
                    "carType": _optional_code(CarType, car_type, "car_type"),
                    "stdDate": std_date,
                    "numOfRows": num_of_rows,
                    "pageNo": page_no,
                },
                dict,
            )
        except KrexError as exc:
            self._client._http.protect_error(exc)
            raise exc from None

    async def flow(
        self,
        *,
        route_no: str | None = None,
        conzone_id: str | None = None,
        direction: FlowDirection | str | None = None,
        num_of_rows: int = 1000,
        page_no: int = 1,
    ) -> Page[TrafficFlow]:
        """0405 전체 응답을 한 번 조회한 뒤 로컬 필터와 페이지 분할을 적용한다."""
        try:
            if isinstance(direction, Direction):
                raise KrexInvalidParameterError(
                    "flow direction requires FlowDirection, not Direction"
                )
            direction_code = _optional_code(FlowDirection, direction, "direction")
            for name, value in (("num_of_rows", num_of_rows), ("page_no", page_no)):
                if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                    raise KrexInvalidParameterError(f"{name} must be a positive integer")
            for name, filter_value in (("route_no", route_no), ("conzone_id", conzone_id)):
                if filter_value is not None and (
                    not isinstance(filter_value, str) or not filter_value.strip()
                ):
                    raise KrexInvalidParameterError(f"{name} must be a non-empty string")
            page = await self.flow_all()
            items = tuple(
                item for item in page.items
                if (route_no is None or item.route_no == route_no)
                and (conzone_id is None or item.conzone_id == conzone_id)
                and (direction_code is None or item.direction == direction_code)
            )
            start = (page_no - 1) * num_of_rows
            return Page(
                items=items[start:start + num_of_rows],
                page_no=page_no,
                num_of_rows=num_of_rows,
                total_count=len(items),
                raw=page.raw,
            )
        except KrexError as exc:
            self._client._http.protect_error(exc)
            raise exc from None

    async def flow_all(self) -> Page[TrafficFlow]:
        """0405 전체 응답 한 개를 검증해 반환한다. 필터·페이지 분할·집계는 하지 않는다.

        각 VDS 행을 보존하며 공통 HTTP 재시도 정책은 그대로 적용한다.
        공급자가 모든 행의 수집시각을 같게 보장한다는 뜻은 아니다.
        """
        try:
            try:
                payload = await self._client._http.get_ex(
                    "/openapi/odtraffic/trafficAmountByRealtime"
                )
            except KrexNotFoundError:
                if self._client.strict_no_data:
                    raise
                return Page(items=(), total_count=0)
            page = _parse_traffic_flow_page(payload)
            return Page(items=page.items, total_count=page.total_count, raw=page.raw)
        except KrexError as exc:
            self._client._http.protect_error(exc)
            raise exc from None

    async def incident(
        self,
        *,
        acc_type_code: str | None = None,
        num_of_rows: int = 1000,
        page_no: int = 1,
    ) -> Page[Incident]:
        """0611 실시간 문자정보(돌발) 조회.

        구 `/openapi/trafficapi/incident`는 포털에서 제거되어 항상 404를
        반환하므로 `/openapi/burstInfo/realTimeSms`를 호출한다.
        """

        try:
            return _validate_realtime_sms_page(
                await self._client._page_ex(
                    "/openapi/burstInfo/realTimeSms",
                    {
                        "accTypeCode": acc_type_code,
                        "numOfRows": num_of_rows,
                        "pageNo": page_no,
                    },
                    _incident,
                )
            )
        except KrexError as exc:
            self._client._http.protect_error(exc)
            raise exc from None

    async def vds_raw(self, **params: Any) -> Page[dict[str, Any]]:
        try:
            return await self._client._page_ex("/openapi/trafficapi/vdsRaw", params, dict)
        except KrexError as exc:
            self._client._http.protect_error(exc)
            raise exc from None

    async def avc_raw(self, *, vds_id: str, std_date: str, **params: Any) -> Page[dict[str, Any]]:
        try:
            _require(vds_id, "vds_id")
            _require(std_date, "std_date")
            query = {"vdsId": vds_id, "stdDate": std_date}
            query.update(params)
            return await self._client._page_ex("/openapi/trafficapi/avcRaw", query, dict)
        except KrexError as exc:
            self._client._http.protect_error(exc)
            raise exc from None


@dataclass(frozen=True, slots=True)
class TollfeeService:
    _client: KrexClient

    async def between_tollgates(
        self,
        *,
        start_unit_code: str,
        end_unit_code: str,
        car_type: CarType | str,
        discount_type: DiscountType | str | None = None,
        num_of_rows: int = 100,
        page_no: int = 1,
    ) -> Page[TollFee]:
        try:
            _require(start_unit_code, "start_unit_code")
            _require(end_unit_code, "end_unit_code")
            return await self._client._page_ex(
                "/openapi/tollfee/tollFeeBetweenTcs",
                {
                    "startUnitCode": start_unit_code,
                    "endUnitCode": end_unit_code,
                    "carType": coerce_code(CarType, car_type, "car_type"),
                    "discountType": _optional_code(DiscountType, discount_type, "discount_type"),
                    "numOfRows": num_of_rows,
                    "pageNo": page_no,
                },
                _toll_fee,
            )
        except KrexError as exc:
            self._client._http.protect_error(exc)
            raise exc from None

    async def tollgate_list(self, *, num_of_rows: int = 1000, page_no: int = 1) -> Page[Tollgate]:
        try:
            return await self._client._page_ex(
                "/openapi/business/openapibusinessunit",
                {"numOfRows": num_of_rows, "pageNo": page_no},
                _tollgate,
            )
        except KrexError as exc:
            self._client._http.protect_error(exc)
            raise exc from None


@dataclass(frozen=True, slots=True)
class RestareaService:
    _client: KrexClient

    async def route_facilities(
        self,
        *,
        route_name: str | None = None,
        direction: str | None = None,
        service_area_name: str | None = None,
        route_code: str | None = None,
        service_area_code: str | None = None,
        num_of_rows: int = 1000,
        page_no: int = 1,
    ) -> Page[RestAreaRouteFacility]:
        try:
            return await self._client._page_ex(
                "/openapi/business/serviceAreaRoute",
                {
                    "routeName": route_name,
                    "direction": direction,
                    "serviceAreaName": service_area_name,
                    "routeCode": route_code,
                    "serviceAreaCode": service_area_code,
                    "numOfRows": num_of_rows,
                    "pageNo": page_no,
                },
                _rest_area_route_facility,
            )
        except KrexError as exc:
            self._client._http.protect_error(exc)
            raise exc from None

    async def list_all(
        self,
        *,
        rest_area_name: str | None = None,
        route_name: str | None = None,
        num_of_rows: int = 1000,
        page_no: int = 1,
    ) -> Page[RestArea]:
        try:
            return await self._client._page_go(
                "https://api.data.go.kr/openapi/tn_pubr_public_rest_area_api",
                {
                    "restAreaNm": rest_area_name,
                    "routeNm": route_name,
                    "numOfRows": num_of_rows,
                    "pageNo": page_no,
                },
                _rest_area,
                standard=True,
            )
        except KrexError as exc:
            self._client._http.protect_error(exc)
            raise exc from None

    async def weather(
        self,
        *,
        sdate: str | date | datetime,
        std_hour: str | int,
    ) -> Page[RestAreaWeather]:
        try:
            return await self._client._page_ex(
                "/openapi/restinfo/restWeatherList",
                {"sdate": _format_sdate(sdate), "stdHour": _format_hour(std_hour)},
                _rest_area_weather,
            )
        except KrexError as exc:
            self._client._http.protect_error(exc)
            raise exc from None

    async def latest_weather(
        self,
        *,
        when: datetime | None = None,
        lookback_hours: int = 48,
    ) -> Page[RestAreaWeather]:
        """`when` 이전 시간대부터 과거로 조회해 비어 있지 않은 첫 페이지를 반환합니다.

        `when`이 naive datetime이면 이미 KST인 것으로 간주합니다. UTC 등 다른
        시간대의 naive datetime을 넘기면 실제 시각과 최대 9시간 오차가
        발생하므로, tzinfo가 있는 datetime을 넘기는 것을 권장합니다.
        """

        try:
            if lookback_hours < 0:
                raise ValueError("lookback_hours must be >= 0")
            if lookback_hours > _MAX_LATEST_WEATHER_LOOKBACK_HOURS:
                raise ValueError(f"lookback_hours must be <= {_MAX_LATEST_WEATHER_LOOKBACK_HOURS}")
            base = _as_kst(when) if when is not None else datetime.now(KST)
            base = base.replace(minute=0, second=0, microsecond=0)
            last_raw: dict[str, Any] | None = None
            for offset in range(lookback_hours + 1):
                target = base - timedelta(hours=offset)
                try:
                    page = await self.weather(sdate=target, std_hour=target.hour)
                except KrexNotFoundError:
                    continue
                if page.items:
                    return page
                last_raw = page.raw
            return Page(items=(), raw=last_raw)
        except KrexError as exc:
            self._client._http.protect_error(exc)
            raise exc from None

    async def food_price(self, **params: Any) -> Page[FoodPrice]:
        try:
            return await self._client._page_ex(
                "/openapi/restinfo/restMenuList", params, _food_price
            )
        except KrexError as exc:
            self._client._http.protect_error(exc)
            raise exc from None

    async def fuel_prices(
        self,
        *,
        route_name: str | None = None,
        direction: str | None = None,
        oil_company: str | None = None,
        service_area_name: str | None = None,
        route_code: str | None = None,
        service_area_code: str | None = None,
        num_of_rows: int = 1000,
        page_no: int = 1,
    ) -> Page[RestAreaFuelPrice]:
        try:
            return await self._client._page_ex(
                "/openapi/business/curStateStation",
                {
                    "routeName": route_name,
                    "direction": direction,
                    "oilCompany": oil_company,
                    "serviceAreaName": service_area_name,
                    "routeCode": route_code,
                    "serviceAreaCode": service_area_code,
                    "numOfRows": num_of_rows,
                    "pageNo": page_no,
                },
                _rest_area_fuel_price,
            )
        except KrexError as exc:
            self._client._http.protect_error(exc)
            raise exc from None

    async def convenience_facilities(
        self,
        *,
        direction: str | None = None,
        service_area_name: str | None = None,
        route_code: str | None = None,
        service_area_code: str | None = None,
        num_of_rows: int = 1000,
        page_no: int = 1,
    ) -> Page[dict[str, Any]]:
        try:
            return await self._client._page_ex(
                "/openapi/business/conveniServiceArea",
                {
                    "direction": direction,
                    "serviceAreaName": service_area_name,
                    "routeCode": route_code,
                    "serviceAreaCode": service_area_code,
                    "numOfRows": num_of_rows,
                    "pageNo": page_no,
                },
                dict,
            )
        except KrexError as exc:
            self._client._http.protect_error(exc)
            raise exc from None

    async def parking(self, **params: Any) -> Page[dict[str, Any]]:
        try:
            return await self._client._page_ex("/openapi/restinfo/restParking", params, dict)
        except KrexError as exc:
            self._client._http.protect_error(exc)
            raise exc from None

    async def wifi(self, **params: Any) -> Page[dict[str, Any]]:
        try:
            return await self._client._page_ex("/openapi/restinfo/restWifi", params, dict)
        except KrexError as exc:
            self._client._http.protect_error(exc)
            raise exc from None

    async def restroom(self, **params: Any) -> Page[dict[str, Any]]:
        try:
            return await self._client._page_ex("/openapi/restinfo/restRestroom", params, dict)
        except KrexError as exc:
            self._client._http.protect_error(exc)
            raise exc from None

    async def disabled_facility(self, **params: Any) -> Page[dict[str, Any]]:
        try:
            return await self._client._page_ex("/openapi/restinfo/restDisabled", params, dict)
        except KrexError as exc:
            self._client._http.protect_error(exc)
            raise exc from None

    async def bus_transit(self, **params: Any) -> Page[dict[str, Any]]:
        try:
            return await self._client._page_ex("/openapi/restinfo/restBus", params, dict)
        except KrexError as exc:
            self._client._http.protect_error(exc)
            raise exc from None


@dataclass(frozen=True, slots=True)
class FacilityService:
    _client: KrexClient

    async def tollgate_info(self, **params: Any) -> Page[dict[str, Any]]:
        try:
            return await self._client._page_go(
                "https://apis.data.go.kr/B552061/TollgateInfoService/getTollgateInfo",
                params,
                dict,
            )
        except KrexError as exc:
            self._client._http.protect_error(exc)
            raise exc from None

    async def drowsy_shelter(self, **params: Any) -> Page[dict[str, Any]]:
        try:
            return await self._client._page_ex("/openapi/restinfo/drowsyShelter", params, dict)
        except KrexError as exc:
            self._client._http.protect_error(exc)
            raise exc from None

    async def shoulder_lane(self, **params: Any) -> Page[dict[str, Any]]:
        try:
            return await self._client._page_go(
                "https://apis.data.go.kr/B552061/ShoulderLaneService/getShoulderLane",
                params,
                dict,
            )
        except KrexError as exc:
            self._client._http.protect_error(exc)
            raise exc from None


@dataclass(frozen=True, slots=True)
class AdminService:
    _client: KrexClient

    async def procurement_contracts(self, **params: Any) -> Page[dict[str, Any]]:
        try:
            return await self._client._page_go(
                "https://apis.data.go.kr/B552061/ProcurementContractService/getContracts",
                params,
                dict,
            )
        except KrexError as exc:
            self._client._http.protect_error(exc)
            raise exc from None


@dataclass(frozen=True, slots=True)
class ReferenceService:
    _client: KrexClient

    def api_catalog(
        self,
        *,
        provider: str | None = None,
        namespace: str | None = None,
    ) -> tuple[ApiCatalogItem, ...]:
        return get_api_catalog(provider=provider, namespace=namespace)

    def routes(self) -> tuple[Route, ...]:
        return tuple(
            Route(route_no=code, route_name=name, short_name=name.replace("고속도로", "선"))
            for code, name in ROUTE_NAMES.items()
        )

    def common_codes(self) -> dict[str, dict[str, str]]:
        return {
            "car_type": {item.value: item.label for item in CarType},
            "tcs_type": {item.value: item.label for item in TCSType},
            "road_operator": {item.value: item.label for item in RoadOperator},
            "in_out": {item.value: item.label for item in IOType},
            "time_unit": {item.value: item.label for item in TimeUnit},
            "direction": {item.value: item.label for item in Direction},
            "congestion": {item.value: item.label for item in CongestionLevel},
            "discount": {item.value: item.label for item in DiscountType},
        }


def _parse_page(payload: NormalizedPayload, parser: Callable[[dict[str, Any]], T]) -> Page[T]:
    parsed = []
    first_error: tuple[Exception, dict[str, Any]] | None = None
    for row in payload.items:
        try:
            parsed.append(parser(row))
        except (KeyError, TypeError, ValueError) as exc:
            if first_error is None:
                first_error = (exc, row)
    if not parsed and first_error is not None:
        error, error_row = first_error
        raise KrexParseError(
            f"failed to parse response record: {error}", response=error_row
        ) from error
    return Page(
        items=tuple(parsed),
        page_no=payload.page_no,
        num_of_rows=payload.num_of_rows,
        total_count=payload.total_count,
        raw=payload.raw,
    )


def _validate_realtime_sms_page(page: Page[Incident]) -> Page[Incident]:
    """실시간 문자정보의 명시적 snapshot envelope를 검증한다.

    이 endpoint는 정상 응답에도 ``code``가 없으므로 EX 공통 success-code만으로는
    오류 본문과 빈 snapshot을 구분할 수 없다. ``realTimeSMSList``와 non-negative
    ``count``가 함께 있을 때만 호출자가 authoritative snapshot으로 사용할 수 있다.
    """
    raw = page.raw
    if not isinstance(raw, dict) or "realTimeSMSList" not in raw:
        raise KrexParseError(
            "realTimeSms response did not contain realTimeSMSList",
            response=raw,
        )
    raw_items = raw["realTimeSMSList"]
    if not isinstance(raw_items, (dict, list)):
        raise KrexParseError(
            "realTimeSms.realTimeSMSList must be an object or list of objects",
            response=raw,
        )
    if "count" not in raw or page.total_count is None or page.total_count < 0:
        raise KrexParseError(
            "realTimeSms response did not contain a non-negative count",
            response=raw,
        )
    if len(page.items) > page.total_count:
        raise KrexParseError(
            "realTimeSms item count exceeded response count",
            response=raw,
        )
    return page


def _traffic_by_ic(row: dict[str, Any]) -> TrafficByIc:
    return TrafficByIc(
        collected_date=to_date_or_none(_get(row, "stdDate", "collectedDate", "sumDate")),
        collected_time=strip_or_none(_get(row, "stdTime", "collectedTime", "sumTm")),
        unit_code=str(_required(row, "unitCode")).strip(),
        unit_name=strip_or_none(_get(row, "unitName")),
        in_out=_enum_or_none(IOType, _get(row, "inOutType", "inoutType")),
        tcs_type=_enum_or_none(TCSType, _get(row, "tcsType")),
        car_type=_enum_or_none(CarType, _get(row, "carType")),
        traffic_volume=to_int_or_none(_get(row, "trafficVol", "trafficVolume", "trafficAmout")),
        raw=row,
    )


def _parse_traffic_flow_page(payload: NormalizedPayload) -> Page[TrafficFlow]:
    """0405는 전체 목록을 반환하므로 누락된 목록·건수·부분 파싱을 거부한다."""
    raw = payload.raw
    raw_items = raw.get("list")
    count = raw.get("count")
    if not isinstance(raw_items, (dict, list)) or raw_items == {}:
        raise KrexParseError("traffic flow response must contain a list or record", response=raw)
    if (
        isinstance(count, bool)
        or not isinstance(count, (int, str))
        or not str(count).isascii()
        or not str(count).isdigit()
        or int(count) != len(payload.items)
    ):
        raise KrexParseError("traffic flow count must match the complete list", response=raw)
    page = _parse_page(payload, _traffic_flow)
    if len(page.items) != len(payload.items):
        raise KrexParseError("traffic flow response contains invalid records", response=raw)
    return page


def _traffic_flow(row: dict[str, Any]) -> TrafficFlow:
    conzone_id = strip_or_none(_required(row, "conzoneId", "conzoneID"))
    direction: FlowDirection | Direction | None = _enum_or_none(
        Direction, _get(row, "dirType", "directionCode")
    )
    if "updownTypeCode" in row:
        # 0405의 S/E는 South/East가 아니라 기점/종점 방향이다.
        direction = FlowDirection(str(row["updownTypeCode"]).strip())
    congestion_level = _enum_or_none(
        CongestionLevel, _get(row, "congestionLevel", "conzoneGrade")
    )
    if "grade" in row:
        congestion_level = {
            "0": None, "1": CongestionLevel.SMOOTH,
            "2": CongestionLevel.SLOW, "3": CongestionLevel.STOP,
        }[str(row["grade"]).strip()]
    updated_at = strip_or_none(_get(row, "updTime", "updateTime", "updatedAt"))
    if "stdDate" in row or "stdHour" in row:
        day = str(_required(row, "stdDate")).strip()
        hour = str(_required(row, "stdHour")).strip()
        if (
            len(day) != 8 or len(hour) != 4
            or not (day + hour).isascii() or not (day + hour).isdigit()
        ):
            raise ValueError("traffic flow stdDate/stdHour must be YYYYMMDD/HHMM")
        updated_at = datetime.strptime(day + hour, "%Y%m%d%H%M").strftime("%Y%m%d%H%M")
    speed = to_float_or_none(_get(row, "speed", "avgSpeed"))
    if speed is not None and speed < 0:
        speed = None
    return TrafficFlow(
        vds_id=strip_or_none(_get(row, "vdsId")),
        conzone_id=conzone_id,
        conzone_name=strip_or_none(_get(row, "conzoneName")),
        route_no=strip_or_none(_get(row, "routeNo")),
        route_name=strip_or_none(_get(row, "routeName")),
        direction=direction,
        speed=speed,
        free_flow_speed=to_float_or_none(_get(row, "tmFreeFlow", "freeFlowSpeed")),
        congestion_level=congestion_level,
        updated_at=updated_at,
        raw=row,
    )


def _incident(row: dict[str, Any]) -> Incident:
    return Incident(
        occurred_date=strip_or_none(_get(row, "accDate")),
        occurred_time=strip_or_none(_get(row, "accHour")),
        incident_type=strip_or_none(_get(row, "accType")),
        incident_type_code=strip_or_none(_get(row, "accTypeCode")),
        direction=strip_or_none(_get(row, "startEndTypeCode")),
        message=strip_or_none(_get(row, "smsText")),
        point_name=strip_or_none(_get(row, "accPointNM")),
        route_no=strip_or_none(_get(row, "nosunNM")),
        route_name=strip_or_none(_get(row, "roadNM")),
        process_status=strip_or_none(_get(row, "accProcessNM")),
        process_status_code=strip_or_none(_get(row, "accProcessCode")),
        latitude=to_float_or_none(_get(row, "latitude")),
        # 포털 명세상 '돌발시작이정경도'(경도)가 `altitude` 키로 내려온다.
        # 키 이름만 보고 고도로 오해하지 말 것.
        longitude=to_float_or_none(_get(row, "altitude")),
        congestion_length=to_float_or_none(_get(row, "lateLength")),
        series_no=to_int_or_none(_get(row, "seriesNM")),
        raw=row,
    )


def _toll_fee(row: dict[str, Any]) -> TollFee:
    return TollFee(
        start_unit_code=str(_required(row, "startUnitCode")),
        start_unit_name=strip_or_none(_get(row, "startUnitName")),
        end_unit_code=str(_required(row, "endUnitCode")),
        end_unit_name=strip_or_none(_get(row, "endUnitName")),
        car_type=_enum_or_none(CarType, _get(row, "carType")),
        discount_type=_enum_or_none(DiscountType, _get(row, "discountType")),
        route_count=to_int_or_none(_get(row, "routeCount")),
        total_length_km=to_float_or_none(_get(row, "totalLength", "totalLengthKm")),
        travel_time_min=to_int_or_none(_get(row, "travelTime", "travelTimeMin")),
        toll_fee=to_int_or_none(_get(row, "tollFee")),
        toll_fee_night=to_int_or_none(_get(row, "tollFeeNight")),
        toll_fee_rush=to_int_or_none(_get(row, "tollFeeRush")),
        raw=row,
    )


def _tollgate(row: dict[str, Any]) -> Tollgate:
    x = to_float_or_none(_get(row, "xValue", "x"))
    y = to_float_or_none(_get(row, "yValue", "y"))
    raw_coordinate = _raw_coordinate(x, y)
    return Tollgate(
        unit_code=str(_required(row, "unitCode")),
        unit_name=str(_required(row, "unitName")),
        route_no=strip_or_none(_get(row, "routeNo")),
        route_name=strip_or_none(_get(row, "routeName")),
        ex_div_code=strip_or_none(_get(row, "exDivCode")),
        x=x,
        y=y,
        head_office_code=strip_or_none(_get(row, "headOfficeCode")),
        branch_office_code=strip_or_none(_get(row, "branchOfficeCode")),
        raw=row,
        raw_coordinate=raw_coordinate,
    )


def _rest_area(row: dict[str, Any]) -> RestArea:
    lon, lat = _wgs84_from_row(row)
    return RestArea(
        name=str(_required(row, "entrpsNm", "restAreaNm", "serviceAreaName")),
        route_name=strip_or_none(_get(row, "routeNm", "routeName")),
        direction=strip_or_none(_get(row, "directionContent", "direction")),
        lat=lat,
        lon=lon,
        has_gas_station=to_bool_yn(_get(row, "gasStnYn")),
        has_lpg_station=to_bool_yn(_get(row, "lpgStnYn")),
        has_ev_charger=to_bool_yn(_get(row, "evChargYn")),
        phone_number=strip_or_none(_get(row, "phoneNumber", "tel")),
        reference_date=to_date_or_none(_get(row, "referenceDate")),
        raw=row,
    )


def _rest_area_route_facility(row: dict[str, Any]) -> RestAreaRouteFacility:
    return RestAreaRouteFacility(
        route_code=strip_or_none(_get(row, "routeCode")),
        service_area_code=str(_required(row, "serviceAreaCode")),
        service_area_code2=strip_or_none(_get(row, "serviceAreaCode2")),
        route_name=strip_or_none(_get(row, "routeName")),
        direction=strip_or_none(_get(row, "direction")),
        service_area_name=strip_or_none(_get(row, "serviceAreaName")),
        phone_number=strip_or_none(_get(row, "telNo", "phoneNumber", "tel")),
        address=strip_or_none(_get(row, "svarAddr", "addr", "address")),
        brand=strip_or_none(_get(row, "brand")),
        convenience=strip_or_none(_get(row, "convenience")),
        has_maintenance=to_bool_yn(_get(row, "maintenanceYn")),
        is_truck_rest_area=to_bool_yn(_get(row, "truckSaYn")),
        representative_food=strip_or_none(_get(row, "batchMenu", "representativeFood")),
        raw=row,
    )


def _rest_area_fuel_price(row: dict[str, Any]) -> RestAreaFuelPrice:
    return RestAreaFuelPrice(
        route_code=strip_or_none(_get(row, "routeCode")),
        service_area_code=str(_required(row, "serviceAreaCode")),
        service_area_code2=strip_or_none(_get(row, "serviceAreaCode2")),
        route_name=strip_or_none(_get(row, "routeName")),
        direction=strip_or_none(_get(row, "direction")),
        oil_company=strip_or_none(_get(row, "oilCompany")),
        has_lpg=to_bool_yn(_get(row, "lpgYn")),
        service_area_name=strip_or_none(_get(row, "serviceAreaName")),
        phone_number=strip_or_none(_get(row, "telNo", "phoneNumber", "tel")),
        address=strip_or_none(_get(row, "svarAddr", "addr", "address")),
        gasoline_price=to_int_or_none(_get(row, "gasolinePrice")),
        diesel_price=to_int_or_none(_get(row, "diselPrice", "dieselPrice")),
        lpg_price=to_int_or_none(_get(row, "lpgPrice")),
        raw=row,
    )


def _rest_area_weather(row: dict[str, Any]) -> RestAreaWeather:
    x = _weather_float_or_none(_get(row, "xValue", "x"))
    y = _weather_float_or_none(_get(row, "yValue", "y"))
    lon, lat = _wgs84_from_lon_lat(x, y)
    return RestAreaWeather(
        observed_at=_parse_rest_area_weather_observed_at(
            _required(row, "sdate"),
            _required(row, "stdHour"),
        ),
        sdate=_format_sdate(_required(row, "sdate")),
        std_hour=_format_hour(_required(row, "stdHour")),
        unit_code=str(_required(row, "unitCode")).strip(),
        unit_name=str(_required(row, "unitName")).strip(),
        route_no=strip_or_none(_get(row, "routeNo")),
        route_name=strip_or_none(_get(row, "routeName")),
        direction_code=strip_or_none(_get(row, "updownTypeCode", "directionCode")),
        lat=lat,
        lon=lon,
        address=strip_or_none(_get(row, "svarAddr", "addr", "address")),
        measurement_station=strip_or_none(_get(row, "measurement", "measurementStation")),
        weather=strip_or_none(_get(row, "weatherContents", "weather")),
        temperature=_weather_float_or_none(_get(row, "tempValue", "temperature")),
        humidity=_weather_float_or_none(_get(row, "humidityValue", "humidity")),
        wind_speed=_weather_float_or_none(_get(row, "windValue", "windSpeed")),
        wind_direction_code=strip_or_none(_get(row, "windContents", "windDirectionCode")),
        rainfall=_weather_float_or_none(_get(row, "rainfallValue", "rainfall")),
        rainfall_strength=_weather_float_or_none(
            _get(row, "rainfallstrengthValue", "rainfallStrengthValue", "rainfallStrength"),
        ),
        new_snow=_weather_float_or_none(_get(row, "newsnowValue", "newSnow")),
        snow=_weather_float_or_none(_get(row, "snowValue", "snow")),
        cloud=_weather_float_or_none(_get(row, "cloudValue", "cloud")),
        dew_point=_weather_float_or_none(_get(row, "dewValue", "dewPoint")),
        raw=row,
        raw_coordinate=_raw_coordinate(x, y),
    )


def _food_price(row: dict[str, Any]) -> FoodPrice:
    return FoodPrice(
        service_area_code=strip_or_none(_get(row, "serviceAreaCode")),
        service_area_name=strip_or_none(_get(row, "serviceAreaName")),
        store_code=strip_or_none(_get(row, "storeCode")),
        store_name=strip_or_none(_get(row, "storeName")),
        food_code=strip_or_none(_get(row, "foodCode")),
        food_name=str(_required(row, "foodName")),
        price=to_int_or_none(_get(row, "price")),
        is_recommended=to_bool_yn(_get(row, "recommendYn")),
        raw=row,
    )


def _clean(params: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in params.items() if value is not None}


def _require(value: str | None, field: str) -> None:
    if not value:
        raise KrexInvalidParameterError(f"{field} must not be empty")


def _as_kst(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=KST)
    return value.astimezone(KST)


def _format_sdate(value: Any) -> str:
    if isinstance(value, datetime):
        return _as_kst(value).strftime("%Y%m%d")
    if isinstance(value, date):
        return value.strftime("%Y%m%d")
    text = str(value).strip()
    if len(text) != 8 or not text.isdigit():
        raise ValueError("sdate must be YYYYMMDD")
    return text


def _format_hour(value: Any) -> str:
    text = str(value).strip()
    if text == "":
        raise ValueError("std_hour must not be empty")
    hour = int(text)
    if not 0 <= hour <= 23:
        raise ValueError("std_hour must be between 0 and 23")
    return f"{hour:02d}"


def _parse_rest_area_weather_observed_at(sdate: Any, std_hour: Any) -> datetime:
    raw = f"{_format_sdate(sdate)}{_format_hour(std_hour)}"
    return datetime.strptime(raw, "%Y%m%d%H").replace(tzinfo=KST)


def _weather_float_or_none(value: Any) -> float | None:
    try:
        number = to_float_or_none(value)
    except ValueError:
        return None
    if number is None or number <= -99.0:
        return None
    return number


def _optional_code(enum_type: type[E], value: E | str | None, field: str) -> str | None:
    if value is None:
        return None
    return coerce_code(enum_type, value, field)


def _enum_or_none(enum_type: type[E], value: Any) -> E | None:
    text = strip_or_none(value)
    if text is None:
        return None
    return enum_type(text)


def _get(row: dict[str, Any], *names: str) -> Any:
    fallback: Any = None
    fallback_found = False
    for name in names:
        if name not in row:
            continue
        value = row[name]
        if strip_or_none(value) is not None:
            return value
        if not fallback_found:
            fallback = value
            fallback_found = True
    return fallback


def _required(row: dict[str, Any], *names: str) -> Any:
    value = _get(row, *names)
    if strip_or_none(value) is None:
        joined = "/".join(names)
        raise ValueError(f"{joined} is required")
    return value


def _wgs84_from_row(row: dict[str, Any]) -> tuple[float | None, float | None]:
    lon = to_float_or_none(_get(row, "lon", "longitude", "lng", "lcLongitude", "경도", "xcoord"))
    lat = to_float_or_none(_get(row, "lat", "latitude", "lcLatitude", "위도", "ycoord"))
    return _wgs84_from_lon_lat(lon, lat)


def _wgs84_from_lon_lat(lon: float | None, lat: float | None) -> tuple[float | None, float | None]:
    if lon is not None and lat is not None and 124 <= lon <= 132 and 33 <= lat <= 39:
        return lon, lat
    return None, None


def _raw_coordinate(x: float | None, y: float | None) -> RawCoordinate | None:
    if x is None or y is None:
        return None
    system = (
        CoordinateSystem.WGS84
        if _wgs84_from_lon_lat(x, y) != (None, None)
        else CoordinateSystem.UNKNOWN
    )
    return RawCoordinate(x=x, y=y, system=system)
