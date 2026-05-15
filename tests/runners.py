from __future__ import annotations

from collections.abc import Callable
from typing import Any

from krex._http import _normalize_ex_payload
from krex.client import _parse_page, _rest_area_weather


def _parse_restarea_weather(raw: dict[str, Any]) -> Any:
    payload = _normalize_ex_payload(raw, params={})
    return _parse_page(payload, _rest_area_weather)


def _identity(value: Any) -> Any:
    return value


RUNNERS: dict[str, dict[str, Callable[[Any], Any]]] = {
    "restarea.weather": {
        "parse": _parse_restarea_weather,
        "process": _identity,
    },
}
