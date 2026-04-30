import pytest

from kex_openapi import CarType, CongestionLevel, Direction, TCSType
from kex_openapi.codes import coerce_code
from kex_openapi.exceptions import KexInvalidParameterError


def test_enum_labels_are_stable() -> None:
    assert CarType.LIGHT.label == "1종"
    assert TCSType.HIPASS.label == "하이패스"
    assert Direction.UP.label == "상행"
    assert CongestionLevel.STOP.label == "정체"


def test_car_type_from_label_accepts_label_or_code() -> None:
    assert CarType.from_label("1종") is CarType.LIGHT
    assert CarType.from_label("1") is CarType.LIGHT


def test_coerce_code_rejects_unknown_values() -> None:
    with pytest.raises(KexInvalidParameterError):
        coerce_code(CarType, "9", "car_type")
