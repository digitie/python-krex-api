from __future__ import annotations

from typing import Any

import pytest
import requests

from krex._http import KexHttp
from krex.exceptions import (
    KexAuthError,
    KexBadRequestError,
    KexConfigError,
    KexConnectionError,
    KexInvalidParameterError,
    KexNotFoundError,
    KexParseError,
    KexQuotaExceededError,
    KexServerError,
)


class FakeResponse:
    def __init__(self, payload: Any = None, *, status_code: int = 200, text: str = "") -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = text

    def json(self) -> Any:
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeSession:
    def __init__(self, *responses: Any) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def get(self, url: str, *, params: dict[str, Any], timeout: float) -> Any:
        self.calls.append({"url": url, "params": params, "timeout": timeout})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def test_get_ex_adds_key_and_normalizes_list() -> None:
    session = FakeSession(
        FakeResponse(
            {
                "code": "SUCCESS",
                "pageNo": "2",
                "numOfRows": "1",
                "count": "9",
                "list": {"a": "1"},
            }
        )
    )
    http = KexHttp(ex_api_key="secret-key", retry_backoff=0, session=session)

    payload = http.get_ex("/openapi/test", {"pageNo": 2})

    assert session.calls[0]["url"] == "https://data.ex.co.kr/openapi/test"
    assert session.calls[0]["params"]["key"] == "secret-key"
    assert session.calls[0]["params"]["type"] == "json"
    assert payload.items == [{"a": "1"}]
    assert payload.page_no == 2
    assert payload.num_of_rows == 1
    assert payload.total_count == 9


def test_none_session_uses_real_session_factory_and_repr_hides_keys() -> None:
    http = KexHttp(ex_api_key="secret-key", go_api_key="go-key", session=None)

    assert http.session is not None
    assert "secret-key" not in repr(http)
    assert "go-key" not in repr(http)


def test_get_go_standard_uses_type_not_underscore_type() -> None:
    session = FakeSession(
        FakeResponse(
            {
                "response": {
                    "header": {"resultCode": "00", "resultMsg": "OK"},
                    "body": {"items": {"item": [{"name": "x"}]}, "totalCount": "1"},
                }
            }
        )
    )
    http = KexHttp(go_api_key="go-key", retry_backoff=0, session=session)

    payload = http.get_go("https://api.example.test/rest", {"pageNo": 1}, standard=True)

    assert session.calls[0]["params"]["serviceKey"] == "go-key"
    assert session.calls[0]["params"]["type"] == "json"
    assert "_type" not in session.calls[0]["params"]
    assert payload.items == [{"name": "x"}]
    assert payload.total_count == 1


def test_get_ex_accepts_endpoint_named_top_level_list() -> None:
    session = FakeSession(
        FakeResponse(
            {
                "code": "SUCCESS",
                "message": "인증키가 유효합니다.",
                "count": 1,
                "trafficIc": [{"unitCode": "101 "}],
            }
        )
    )
    http = KexHttp(ex_api_key="secret-key", retry_backoff=0, session=session)

    payload = http.get_ex("/openapi/trafficapi/trafficIc")

    assert payload.items == [{"unitCode": "101 "}]
    assert payload.total_count == 1


def test_get_ex_preserves_zero_count() -> None:
    http = KexHttp(
        ex_api_key="secret-key",
        retry_backoff=0,
        session=FakeSession(FakeResponse({"code": "SUCCESS", "count": 0, "list": []})),
    )

    payload = http.get_ex("/openapi/trafficapi/trafficRoute")

    assert payload.items == []
    assert payload.total_count == 0


@pytest.mark.parametrize(
    ("code", "exc_type"),
    [
        ("INVALID_KEY", KexAuthError),
        ("EXCEEDED_LIMIT", KexQuotaExceededError),
        ("INVALID_PARAMETER_VALUE", KexInvalidParameterError),
        ("NO_DATA", KexNotFoundError),
        ("SYSTEM_ERROR", KexServerError),
    ],
)
def test_data_ex_error_codes_are_typed(code: str, exc_type: type[Exception]) -> None:
    http = KexHttp(
        ex_api_key="key",
        retry_backoff=0,
        session=FakeSession(FakeResponse({"code": code})),
    )

    with pytest.raises(exc_type):
        http.get_ex("/openapi/test")


@pytest.mark.parametrize(
    ("code", "exc_type"),
    [
        ("03", KexNotFoundError),
        ("10", KexInvalidParameterError),
        ("11", KexBadRequestError),
        ("22", KexQuotaExceededError),
        ("30", KexAuthError),
    ],
)
def test_data_go_error_codes_are_typed(code: str, exc_type: type[Exception]) -> None:
    payload = {"response": {"header": {"resultCode": code, "resultMsg": "ERR"}, "body": {}}}
    http = KexHttp(go_api_key="key", retry_backoff=0, session=FakeSession(FakeResponse(payload)))

    with pytest.raises(exc_type):
        http.get_go("https://api.example.test")


def test_5xx_retries_then_succeeds() -> None:
    session = FakeSession(
        FakeResponse(status_code=500, text="down"),
        FakeResponse({"code": "SUCCESS", "list": [{"ok": "yes"}]}),
    )
    http = KexHttp(ex_api_key="key", retry_backoff=0, max_retries=1, session=session)

    payload = http.get_ex("/openapi/test")

    assert len(session.calls) == 2
    assert payload.items == [{"ok": "yes"}]


def test_connection_error_retries_then_raises() -> None:
    session = FakeSession(requests.ConnectionError("offline"), requests.ConnectionError("offline"))
    http = KexHttp(ex_api_key="secret-key", retry_backoff=0, max_retries=1, session=session)

    with pytest.raises(KexConnectionError) as raised:
        http.get_ex("/openapi/test")

    assert raised.value.params is not None
    assert raised.value.params["key"] == "secr..."
    assert len(session.calls) == 2


def test_json_parse_failure_maps_to_parse_error() -> None:
    http = KexHttp(
        ex_api_key="key",
        retry_backoff=0,
        session=FakeSession(FakeResponse(ValueError("bad json"))),
    )

    with pytest.raises(KexParseError):
        http.get_ex("/openapi/test")


def test_missing_keys_raise_auth_errors() -> None:
    with pytest.raises(KexAuthError):
        KexHttp(session=FakeSession()).get_ex("/openapi/test")
    with pytest.raises(KexAuthError):
        KexHttp(session=FakeSession()).get_go("https://api.example.test")


@pytest.mark.parametrize(
    ("status", "exc_type"),
    [
        (400, KexBadRequestError),
        (401, KexAuthError),
        (403, KexAuthError),
        (404, KexBadRequestError),
        (429, KexQuotaExceededError),
        (500, KexServerError),
    ],
)
def test_http_status_codes_are_typed(status: int, exc_type: type[Exception]) -> None:
    http = KexHttp(
        ex_api_key="key",
        retry_backoff=0,
        max_retries=0,
        session=FakeSession(FakeResponse(status_code=status, text="problem")),
    )

    with pytest.raises(exc_type):
        http.get_ex("/openapi/test")


def test_malformed_go_envelope_is_parse_error() -> None:
    http = KexHttp(
        go_api_key="key",
        retry_backoff=0,
        session=FakeSession(FakeResponse({"response": {}})),
    )

    with pytest.raises(KexParseError):
        http.get_go("https://api.example.test")


def test_load_requests_missing_is_config_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    real_import = builtins.__import__

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "requests":
            raise ModuleNotFoundError("requests")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(KexConfigError):
        KexHttp(ex_api_key="key", session=FakeSession()).get_ex("/openapi/test")
