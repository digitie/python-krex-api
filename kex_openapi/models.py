"""Public Pydantic models returned by kex-openapi."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, field_validator

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


class KexModel(BaseModel):
    """Base class for immutable public response models."""

    model_config = ConfigDict(frozen=True, use_enum_values=False)


class Page(KexModel, Generic[T]):
    items: tuple[T, ...]
    page_no: int | None = None
    num_of_rows: int | None = None
    total_count: int | None = None
    raw: dict[str, Any] | None = None

    def __iter__(self) -> Iterator[T]:  # type: ignore[override]
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


class GeoPoint(KexModel):
    """Standard WGS84 longitude/latitude point.

    `lon` comes first to match GeoJSON and most GIS APIs. The `latlon` property
    is available for UI libraries that expect `(lat, lon)`.
    """

    lon: float
    lat: float

    @field_validator("lon")
    @classmethod
    def _validate_lon(cls, value: float) -> float:
        if not -180 <= value <= 180:
            raise ValueError("lon must be between -180 and 180")
        return value

    @field_validator("lat")
    @classmethod
    def _validate_lat(cls, value: float) -> float:
        if not -90 <= value <= 90:
            raise ValueError("lat must be between -90 and 90")
        return value

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


class RawCoordinate(KexModel):
    x: float
    y: float
    system: CoordinateSystem = CoordinateSystem.UNKNOWN


class TrafficByIc(KexModel):
    collected_date: date | None
    collected_time: str | None
    unit_code: str
    unit_name: str | None
    in_out: IOType | None
    tcs_type: TCSType | None
    car_type: CarType | None
    traffic_volume: int | None
    raw: dict[str, Any]


class TrafficFlow(KexModel):
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


class Incident(KexModel):
    route_no: str | None
    route_name: str | None
    direction: Direction | None
    incident_type: str | None
    message: str | None
    started_at: str | None
    ended_at: str | None
    raw: dict[str, Any]


class TollFee(KexModel):
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


class Tollgate(KexModel):
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


class RestArea(KexModel):
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


class FoodPrice(KexModel):
    service_area_code: str | None
    service_area_name: str | None
    store_code: str | None
    store_name: str | None
    food_code: str | None
    food_name: str
    price: int | None
    is_recommended: bool | None
    raw: dict[str, Any]


class Route(KexModel):
    route_no: str
    route_name: str
    short_name: str | None = None
