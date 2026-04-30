"""Enums and code mappings used by Korea Expressway Corporation APIs."""

from __future__ import annotations

from enum import StrEnum
from typing import TypeVar

from .exceptions import KexInvalidParameterError

E = TypeVar("E", bound=StrEnum)


def coerce_code(enum_type: type[E], value: E | str, field: str) -> str:
    """Return a raw API code after validating enum-compatible input."""

    try:
        return enum_type(value).value
    except ValueError as exc:
        allowed = ", ".join(item.value for item in enum_type)
        raise KexInvalidParameterError(f"{field} must be one of: {allowed}") from exc


class CarType(StrEnum):
    LIGHT = "1"
    MEDIUM = "2"
    LARGE_3AXLE = "3"
    LARGE_4AXLE = "4"
    LARGE_5AXLE = "5"
    LIGHT_DISCOUNT = "6"

    @property
    def label(self) -> str:
        return _CAR_TYPE_LABELS[self.value]

    @classmethod
    def from_label(cls, label: str) -> "CarType":
        return _from_label(cls, _CAR_TYPE_LABELS, label)


class TCSType(StrEnum):
    ALL = "0"
    TCS = "1"
    HIPASS = "2"

    @property
    def label(self) -> str:
        return _TCS_TYPE_LABELS[self.value]


class RoadOperator(StrEnum):
    KEC = "00"
    PRIV_INCHEON_AIRPORT = "01"
    PRIV_CHEONAN_NONSAN = "02"
    PRIV_DAEGU_BUSAN = "08"
    PRIV_SEOUL_CHUNCHEON = "11"
    PRIV_GURIPOCHEON = "18"

    @property
    def label(self) -> str:
        return _ROAD_OPERATOR_LABELS.get(self.value, self.value)


class IOType(StrEnum):
    IN = "0"
    OUT = "1"

    @property
    def label(self) -> str:
        return _IO_TYPE_LABELS[self.value]


class TimeUnit(StrEnum):
    HOUR = "1"
    MIN_15 = "2"

    @property
    def label(self) -> str:
        return _TIME_UNIT_LABELS[self.value]


class Direction(StrEnum):
    UP = "0"
    DOWN = "1"
    EAST = "E"
    WEST = "W"
    SOUTH = "S"
    NORTH = "N"

    @property
    def label(self) -> str:
        return _DIRECTION_LABELS[self.value]


class CongestionLevel(StrEnum):
    SMOOTH = "1"
    SLOW = "2"
    DELAY = "3"
    STOP = "4"

    @property
    def label(self) -> str:
        return _CONGESTION_LABELS[self.value]


class DiscountType(StrEnum):
    NONE = "0"
    NIGHT = "1"
    RUSH_DISCOUNT = "2"
    LIGHT_CAR = "3"
    HYBRID = "4"
    DISABLED = "5"

    @property
    def label(self) -> str:
        return _DISCOUNT_LABELS[self.value]


_CAR_TYPE_LABELS = {
    "1": "1종",
    "2": "2종",
    "3": "3종",
    "4": "4종",
    "5": "5종",
    "6": "경차",
}
_TCS_TYPE_LABELS = {"0": "전체", "1": "TCS", "2": "하이패스"}
_ROAD_OPERATOR_LABELS = {
    "00": "한국도로공사",
    "01": "신공항하이웨이",
    "02": "천안논산고속도로",
    "08": "대구부산고속도로",
    "11": "서울춘천고속도로",
    "18": "서울북부고속도로",
}
_IO_TYPE_LABELS = {"0": "진입", "1": "진출"}
_TIME_UNIT_LABELS = {"1": "1시간", "2": "15분"}
_DIRECTION_LABELS = {
    "0": "상행",
    "1": "하행",
    "E": "동쪽",
    "W": "서쪽",
    "S": "남쪽",
    "N": "북쪽",
}
_CONGESTION_LABELS = {"1": "원활", "2": "서행", "3": "지체", "4": "정체"}
_DISCOUNT_LABELS = {
    "0": "정상",
    "1": "심야",
    "2": "출퇴근",
    "3": "경차",
    "4": "친환경차",
    "5": "장애인",
}


def _from_label(enum_type: type[E], labels: dict[str, str], label: str) -> E:
    normalized = label.strip()
    for code, item_label in labels.items():
        if normalized in {code, item_label}:
            return enum_type(code)
    raise KexInvalidParameterError(f"unknown {enum_type.__name__} label: {label!r}")


ROUTE_NAMES: dict[str, str] = {
    "0010": "경부고속도로",
    "0050": "영동고속도로",
    "0100": "남해고속도로",
    "0150": "서해안고속도로",
    "0200": "평택제천고속도로",
    "0250": "호남고속도로",
    "0270": "익산포항고속도로",
    "0300": "대전통영고속도로",
    "0350": "중부내륙고속도로",
    "0370": "중부고속도로",
    "0400": "평택파주고속도로",
    "0450": "중앙고속도로",
    "0500": "동해고속도로",
    "0550": "순천완주고속도로",
    "0600": "서울양양고속도로",
    "0650": "당진영덕고속도로",
}
