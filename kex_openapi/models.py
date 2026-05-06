"""Public dataclasses returned by kex-openapi."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from typing import Any, Generic, TypeVar

from .codes import (
    CarType,
    CongestionLevel,
    CoordinateSystem,
    Direction,
    DiscountType,
    IOType,
    TCSType,
)

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class Page(Generic[T]):
    items: tuple[T, ...]
    page_no: int | None = None
    num_of_rows: int | None = None
    total_count: int | None = None
    raw: dict[str, Any] | None = None

    def __iter__(self) -> Iterator[T]:
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)

    def __bool__(self) -> bool:
        return bool(self.items)

    @property
    def first(self) -> T | None:
        return self.items[0] if self.items else None

    @property
    def is_empty(self) -> bool:
        return not self.items


@dataclass(frozen=True, slots=True)
class GeoPoint:
    """Standard WGS84 longitude/latitude point.

    `lon` comes first to match GeoJSON and most GIS APIs. The `latlon` property
    is available for UI libraries that expect `(lat, lon)`.
    """

    lon: float
    lat: float

    def __post_init__(self) -> None:
        if not -180 <= self.lon <= 180:
            raise ValueError("lon must be between -180 and 180")
        if not -90 <= self.lat <= 90:
            raise ValueError("lat must be between -90 and 90")

    @property
    def longitude(self) -> float:
        return self.lon

    @property
    def latitude(self) -> float:
        return self.lat

    @property
    def lonlat(self) -> tuple[float, float]:
        return (self.lon, self.lat)

    @property
    def latlon(self) -> tuple[float, float]:
        return (self.lat, self.lon)

    def as_geojson_position(self) -> tuple[float, float]:
        return self.lonlat


@dataclass(frozen=True, slots=True)
class RawCoordinate:
    x: float
    y: float
    system: CoordinateSystem = CoordinateSystem.UNKNOWN



@dataclass(frozen=True, slots=True)
class TrafficByIc:
    collected_date: date | None
    collected_time: str | None
    unit_code: str
    unit_name: str | None
    in_out: IOType | None
    tcs_type: TCSType | None
    car_type: CarType | None
    traffic_volume: int | None
    raw: dict[str, Any]


@dataclass(frozen=True, slots=True)
class TrafficFlow:
    conzone_id: str | None
    conzone_name: str | None
    route_no: str | None
    route_name: str | None
    direction: Direction | None
    speed: float | None
    free_flow_speed: float | None
    congestion_level: CongestionLevel | None
    updated_at: str | None
    raw: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Incident:
    route_no: str | None
    route_name: str | None
    direction: Direction | None
    incident_type: str | None
    message: str | None
    started_at: str | None
    ended_at: str | None
    raw: dict[str, Any]


@dataclass(frozen=True, slots=True)
class TollFee:
    start_unit_code: str
    start_unit_name: str | None
    end_unit_code: str
    end_unit_name: str | None
    car_type: CarType | None
    discount_type: DiscountType | None
    route_count: int | None
    total_length_km: float | None
    travel_time_min: int | None
    toll_fee: int | None
    toll_fee_night: int | None
    toll_fee_rush: int | None
    raw: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Tollgate:
    unit_code: str
    unit_name: str
    route_no: str | None
    route_name: str | None
    ex_div_code: str | None
    x: float | None
    y: float | None
    head_office_code: str | None
    branch_office_code: str | None
    raw: dict[str, Any]
    coordinate: GeoPoint | None = None
    raw_coordinate: RawCoordinate | None = None


@dataclass(frozen=True, slots=True)
class RestArea:
    name: str
    route_name: str | None
    direction: str | None
    lat: float | None
    lon: float | None
    has_gas_station: bool | None
    has_lpg_station: bool | None
    has_ev_charger: bool | None
    phone_number: str | None
    reference_date: date | None
    raw: dict[str, Any]
    coordinate: GeoPoint | None = None


@dataclass(frozen=True, slots=True)
class FoodPrice:
    service_area_code: str | None
    service_area_name: str | None
    store_code: str | None
    store_name: str | None
    food_code: str | None
    food_name: str
    price: int | None
    is_recommended: bool | None
    raw: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Route:
    route_no: str
    route_name: str
    short_name: str | None = None
