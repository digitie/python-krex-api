from __future__ import annotations

from typing import Any

import httpx
import pytest

from krex._http import KrexHttp
from krex.exceptions import (
    KrexAuthError,
    KrexBadRequestError,
    KrexConfigError,
    KrexConnectionError,
    KrexInvalidParameterError,
    KrexNotFoundError,
    KrexParseError,
    KrexQuotaExceededError,
    KrexServerError,
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

    async def get(self, url: str, *, params: dict[str, Any], timeout: float) -> Any:
        self.calls.append({"url": url, "params": params, "timeout": timeout})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


async def test_get_ex_adds_key_and_normalizes_list() -> None:
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
    http = KrexHttp(ex_api_key="secret-key", retry_backoff=0, session=session)

    payload = await http.get_ex("/openapi/test", {"pageNo": 2})

    assert session.calls[0]["url"] == "https://data.ex.co.kr/openapi/test"
    assert session.calls[0]["params"]["key"] == "secret-key"
    assert session.calls[0]["params"]["type"] == "json"
    assert payload.items == [{"a": "1"}]
    assert payload.page_no == 2
    assert payload.num_of_rows == 1
    assert payload.total_count == 9


def test_none_session_uses_real_session_factory_and_repr_hides_keys() -> None:
    http = KrexHttp(ex_api_key="secret-key", go_api_key="go-key", session=None)

    assert http.session is None
    assert "secret-key" not in repr(http)
    assert "go-key" not in repr(http)


async def test_async_get_ex_awaits_async_session() -> None:
    class AsyncFakeSession(FakeSession):
        async def get(self, url: str, *, params: dict[str, Any], timeout: float) -> Any:
            return await super().get(url, params=params, timeout=timeout)

    session = AsyncFakeSession(FakeResponse({"code": "SUCCESS", "list": [{"ok": "yes"}]}))
    http = KrexHttp(ex_api_key="secret-key", retry_backoff=0, session=session)

    payload = await http.get_ex("/openapi/test")

    assert payload.items == [{"ok": "yes"}]
    assert session.calls[0]["params"]["key"] == "secret-key"


async def test_get_go_standard_uses_type_not_underscore_type() -> None:
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
    http = KrexHttp(go_api_key="go-key", retry_backoff=0, session=session)

    payload = await http.get_go("https://api.example.test/rest", {"pageNo": 1}, standard=True)

    assert session.calls[0]["params"]["serviceKey"] == "go-key"
    assert session.calls[0]["params"]["type"] == "json"
    assert "_type" not in session.calls[0]["params"]
    assert payload.items == [{"name": "x"}]
    assert payload.total_count == 1


async def test_api_keys_strip_copy_paste_whitespace() -> None:
    session = FakeSession(
        FakeResponse({"code": "SUCCESS", "list": [{"ok": "ex"}]}),
        FakeResponse(
            {
                "response": {
                    "header": {"resultCode": "00", "resultMsg": "OK"},
                    "body": {"items": {"item": [{"ok": "go"}]}},
                }
            }
        ),
    )
    http = KrexHttp(
        ex_api_key=" secret\r\n-key\t ",
        go_api_key=" go \n key ",
        retry_backoff=0,
        session=session,
    )

    assert (await http.get_ex("/openapi/test")).items == [{"ok": "ex"}]
    assert (await http.get_go("https://api.example.test/rest")).items == [{"ok": "go"}]

    assert session.calls[0]["params"]["key"] == "secret-key"
    assert session.calls[1]["params"]["serviceKey"] == "gokey"


async def test_get_ex_accepts_endpoint_named_top_level_list() -> None:
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
    http = KrexHttp(ex_api_key="secret-key", retry_backoff=0, session=session)

    payload = await http.get_ex("/openapi/trafficapi/trafficIc")

    assert payload.items == [{"unitCode": "101 "}]
    assert payload.total_count == 1


async def test_get_ex_preserves_zero_count() -> None:
    http = KrexHttp(
        ex_api_key="secret-key",
        retry_backoff=0,
        session=FakeSession(FakeResponse({"code": "SUCCESS", "count": 0, "list": []})),
    )

    payload = await http.get_ex("/openapi/trafficapi/trafficRoute")

    assert payload.items == []
    assert payload.total_count == 0


@pytest.mark.parametrize(
    ("code", "exc_type"),
    [
        ("INVALID_KEY", KrexAuthError),
        ("EXCEEDED_LIMIT", KrexQuotaExceededError),
        ("INVALID_PARAMETER_VALUE", KrexInvalidParameterError),
        ("NO_DATA", KrexNotFoundError),
        ("SYSTEM_ERROR", KrexServerError),
    ],
)
async def test_data_ex_error_codes_are_typed(code: str, exc_type: type[Exception]) -> None:
    http = KrexHttp(
        ex_api_key="key",
        retry_backoff=0,
        session=FakeSession(FakeResponse({"code": code})),
    )

    with pytest.raises(exc_type):
        (await http.get_ex("/openapi/test"))


@pytest.mark.parametrize(
    ("code", "exc_type"),
    [
        ("03", KrexNotFoundError),
        ("10", KrexInvalidParameterError),
        ("11", KrexBadRequestError),
        ("22", KrexQuotaExceededError),
        ("30", KrexAuthError),
    ],
)
async def test_data_go_error_codes_are_typed(code: str, exc_type: type[Exception]) -> None:
    payload = {"response": {"header": {"resultCode": code, "resultMsg": "ERR"}, "body": {}}}
    http = KrexHttp(go_api_key="key", retry_backoff=0, session=FakeSession(FakeResponse(payload)))

    with pytest.raises(exc_type):
        (await http.get_go("https://api.example.test"))


async def test_5xx_retries_then_succeeds() -> None:
    session = FakeSession(
        FakeResponse(status_code=500, text="down"),
        FakeResponse({"code": "SUCCESS", "list": [{"ok": "yes"}]}),
    )
    http = KrexHttp(ex_api_key="key", retry_backoff=0, max_retries=1, session=session)

    payload = await http.get_ex("/openapi/test")

    assert len(session.calls) == 2
    assert payload.items == [{"ok": "yes"}]


async def test_connection_error_retries_then_raises() -> None:
    session = FakeSession(httpx.ConnectError("offline"), httpx.ConnectError("offline"))
    http = KrexHttp(ex_api_key="secret-key", retry_backoff=0, max_retries=1, session=session)

    with pytest.raises(KrexConnectionError) as raised:
        (await http.get_ex("/openapi/test"))

    assert raised.value.params is not None
    assert raised.value.params["key"] == "<REDACTED>"
    assert len(session.calls) == 2


async def test_json_parse_failure_maps_to_parse_error() -> None:
    http = KrexHttp(
        ex_api_key="key",
        retry_backoff=0,
        session=FakeSession(FakeResponse(ValueError("bad json"))),
    )

    with pytest.raises(KrexParseError):
        (await http.get_ex("/openapi/test"))


async def test_missing_keys_raise_auth_errors() -> None:
    with pytest.raises(KrexAuthError):
        (await KrexHttp(session=FakeSession()).get_ex("/openapi/test"))
    with pytest.raises(KrexAuthError):
        (await KrexHttp(session=FakeSession()).get_go("https://api.example.test"))


@pytest.mark.parametrize(
    ("status", "exc_type"),
    [
        (400, KrexBadRequestError),
        (401, KrexAuthError),
        (403, KrexAuthError),
        (404, KrexBadRequestError),
        (429, KrexQuotaExceededError),
        (500, KrexServerError),
    ],
)
async def test_http_status_codes_are_typed(status: int, exc_type: type[Exception]) -> None:
    http = KrexHttp(
        ex_api_key="key",
        retry_backoff=0,
        max_retries=0,
        session=FakeSession(FakeResponse(status_code=status, text="problem")),
    )

    with pytest.raises(exc_type):
        (await http.get_ex("/openapi/test"))


async def test_malformed_go_envelope_is_parse_error() -> None:
    http = KrexHttp(
        go_api_key="key",
        retry_backoff=0,
        session=FakeSession(FakeResponse({"response": {}})),
    )

    with pytest.raises(KrexParseError):
        (await http.get_go("https://api.example.test"))


async def test_load_httpx_missing_is_config_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    real_import = builtins.__import__

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "httpx":
            raise ModuleNotFoundError("httpx")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(KrexConfigError):
        (await KrexHttp(ex_api_key="key", session=FakeSession()).get_ex("/openapi/test"))


class _TimestampSession(FakeSession):
    """호출 시각을 남기는 fake — TPS를 **효과로** 재기 위한 것이다."""

    def __init__(self, *responses: Any) -> None:
        super().__init__(*responses)
        self.timestamps: list[float] = []

    async def get(self, url: str, *, params: dict[str, Any], timeout: float) -> Any:
        import time as _time

        self.timestamps.append(_time.monotonic())
        return await super().get(url, params=params, timeout=timeout)


def _ok() -> FakeResponse:
    return FakeResponse({"code": "SUCCESS", "list": {"a": "1"}})


async def test_requests_do_not_exceed_the_configured_tps() -> None:
    """krex의 제약은 일일 한도가 아니라 **TPS**다 — 5건/초를 넘지 않는다.

    숫자를 박아 두는 대신 **나간 시각**을 본다. 상한이 사라지거나 버킷이 요청을
    세지 않게 되면 창 안의 호출 수가 늘어 여기서 빨개진다.
    """

    burst = 8
    max_rps = 5.0
    session = _TimestampSession(*[_ok() for _ in range(burst)])
    http = KrexHttp(ex_api_key="k", retry_backoff=0, session=session, max_rps=max_rps)

    for _ in range(burst):
        (await http.get_ex("/openapi/test"))

    assert len(session.timestamps) == burst
    # **어느 1초 창에서도** 상한을 넘지 않는다 — 시작점만 보면 버스트를 놓친다.
    worst = max(
        sum(1 for t in session.timestamps if start <= t < start + 1.0)
        for start in session.timestamps
    )
    assert worst <= max_rps, (
        f"어떤 1초 창에 {worst}건이 나갔다(상한 {max_rps}). krex는 TPS 제약이라 "
        "초당 건수가 곧 계약이고, 버스트도 그 창 안에서는 초과다."
    )
    # 그리고 8건이 즉시 끝나지 않는다 — 버스트가 상한을 우회하지 못한다.
    assert session.timestamps[-1] - session.timestamps[0] >= (burst - 1) / max_rps


async def test_retries_are_counted_as_requests_for_tps() -> None:
    """**재시도도 요청이다.** 시도 수가 아니라 나가는 건수로 센다.

    버킷을 재시도 루프 **밖**에 두면 재시도가 상한을 넘어 나간다 — 이 저장소가
    분자에서 같은 형태를 이미 한 번 겪었다(계수 자리를 루프 밖에 두면 한 번만 센다).
    """

    max_rps = 2.0
    session = _TimestampSession(httpx.ConnectError("boom"), httpx.ConnectError("boom"), _ok())
    http = KrexHttp(
        ex_api_key="k", retry_backoff=0, session=session, max_rps=max_rps, max_retries=2
    )

    (await http.get_ex("/openapi/test"))

    assert len(session.timestamps) == 3, "재시도 두 번이 실제로 나가야 이 검사가 의미 있다"
    elapsed = session.timestamps[-1] - session.timestamps[0]
    assert elapsed >= 1.0 / max_rps, (
        f"재시도 3건이 {elapsed:.3f}s에 나갔다 — 버킷이 재시도를 세지 않는다."
    )


def test_the_default_is_five_tps() -> None:
    """기본값이 곧 계약이다 — 설정하지 않은 호출자도 5를 넘지 않아야 한다."""

    from krex._http import DEFAULT_MAX_RPS

    assert DEFAULT_MAX_RPS == 5.0
    assert KrexHttp(ex_api_key="k").max_rps == 5.0
