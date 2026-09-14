"""한국도로공사 API용 HTTP 헬퍼."""

from __future__ import annotations

import asyncio
import inspect
import logging
import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote, quote_plus

from ._convert import normalize_items, to_int_or_none
from ._httpx import send_after_token
from ._ratelimit import AsyncTokenBucket
from .exceptions import (
    KrexAuthError,
    KrexBadRequestError,
    KrexConfigError,
    KrexConnectionError,
    KrexError,
    KrexInvalidParameterError,
    KrexMissingParameterError,
    KrexNotFoundError,
    KrexParseError,
    KrexQuotaExceededError,
    KrexServerError,
    KrexServiceUnavailableError,
    KrexTimeoutError,
)

_MAX_BACKOFF_SECONDS = 30.0
_KEY_QUERY = re.compile(r"(?i)([?&](?:key|servicekey)=)[^&\s\"<>]+")


class _KeyLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = _KEY_QUERY.sub(r"\1<REDACTED>", record.getMessage())
        record.args = ()
        return True


logging.getLogger("httpx").addFilter(_KeyLogFilter())


def _load_httpx() -> Any:
    try:
        import httpx
    except ModuleNotFoundError as exc:
        raise KrexConfigError("httpx is required; install python-krex-api dependencies") from exc
    return httpx


@dataclass(frozen=True, slots=True)
class NormalizedPayload:
    items: list[dict[str, Any]]
    page_no: int | None
    num_of_rows: int | None
    total_count: int | None
    raw: dict[str, Any]


DEFAULT_MAX_RPS: float = 5.0
"""기본 요청 속도. 버스트를 허용하지 않는 capacity=1을 사용한다."""


@dataclass(slots=True)
class KrexHttp:
    ex_api_key: str | None = field(default=None, repr=False)
    go_api_key: str | None = field(default=None, repr=False)
    timeout: float = 10.0
    max_retries: int = 2
    retry_backoff: float = 0.5
    session: Any | None = field(default=None, repr=False)
    ex_base_url: str = "https://data.ex.co.kr"
    max_rps: float = DEFAULT_MAX_RPS
    """초당 요청 상한. krex의 제약은 일일 한도가 아니라 TPS다(기본 5)."""
    rate_limiter: AsyncTokenBucket | None = None
    _closed: bool = field(default=False, init=False, repr=False)
    _owns_session: bool = field(default=False, init=False, repr=False)
    _diagnostics: ContextVar[dict[str, Any] | None] = field(
        default_factory=lambda: ContextVar("krex_diagnostics", default=None), init=False, repr=False
    )

    def __post_init__(self) -> None:
        self.ex_api_key = normalize_api_key(self.ex_api_key)
        self.go_api_key = normalize_api_key(self.go_api_key)
        if self.rate_limiter is None:
            self.rate_limiter = AsyncTokenBucket(self.max_rps, capacity=1)
        if self.session is not None and not inspect.iscoroutinefunction(self.session.get):
            raise TypeError("session must provide an async get method")
        self._owns_session = self.session is None

    @property
    def last_request(self) -> dict[str, Any] | None:
        return (self._diagnostics.get() or {}).get("request")

    @last_request.setter
    def last_request(self, value: dict[str, Any] | None) -> None:
        self._diagnostics.set({**(self._diagnostics.get() or {}), "request": value})

    @property
    def last_response(self) -> dict[str, Any] | None:
        return (self._diagnostics.get() or {}).get("response")

    @last_response.setter
    def last_response(self, value: dict[str, Any] | None) -> None:
        self._diagnostics.set({**(self._diagnostics.get() or {}), "response": value})

    @contextmanager
    def capture_calls(self) -> Iterator[None]:
        """현재 진단 호출을 격리하고 취소·예외 시에도 복구한다."""
        token = self._diagnostics.set(None)
        try:
            yield
        finally:
            self._diagnostics.reset(token)

    def protect_error(self, exc: KrexError) -> None:
        """오류 종류를 판별한 후 외부 표시와 첨부 응답에서 키를 제거한다."""
        secrets = (self.ex_api_key, self.go_api_key)
        exc.message = _redact_secrets(str(exc), secrets)
        exc.args = (exc.message,)
        if exc.code is not None:
            exc.code = _redact_secrets(exc.code, secrets)
        exc.response = _redact_payload(exc.response, secrets)
        exc.params = _redact_payload(exc.params, secrets)
        if exc.url is not None:
            exc.url = _redact_secrets(exc.url, secrets)

    async def get_ex(self, path: str, params: dict[str, Any] | None = None) -> NormalizedPayload:
        key = normalize_api_key(self.ex_api_key)
        if not key:
            raise KrexAuthError("KEX_EX_API_KEY is not set and ex_api_key was not provided")
        query = dict(params) if params else {}
        query["key"] = key
        query["type"] = "json"
        url = f"{self.ex_base_url.rstrip('/')}/{path.lstrip('/')}"
        return await self._get(url, query, provider="ex")

    async def get_go(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        *,
        standard: bool = False,
    ) -> NormalizedPayload:
        key = normalize_api_key(self.go_api_key)
        if not key:
            raise KrexAuthError("DATA_GO_KR_SERVICE_KEY is not set and go_api_key was not provided")
        query = dict(params) if params else {}
        query["serviceKey"] = key
        query["type" if standard else "_type"] = "json"
        return await self._get(url, query, provider="go")

    async def _get(self, url: str, params: dict[str, Any], *, provider: str) -> NormalizedPayload:
        if self._closed:
            raise RuntimeError("Krex transport is closed")
        httpx = _load_httpx()
        self._validate_auth(httpx)
        attempts = max(0, self.max_retries) + 1
        self.last_request = {"method": "GET", "url": url, "query": _mask_params(params)}
        self.last_response = None
        if self.session is None:
            self.session = httpx.AsyncClient(timeout=self.timeout, follow_redirects=True)
        secrets = (self.ex_api_key, self.go_api_key)
        try:
            for attempt in range(attempts):
                assert self.rate_limiter is not None
                await self.rate_limiter.acquire()
                if self._closed:
                    raise RuntimeError("Krex transport is closed")
                self._validate_auth(httpx)
                try:
                    if isinstance(self.session, httpx.AsyncClient):
                        request = self.session.build_request(
                            "GET", url, params=params, timeout=self.timeout
                        )
                        response = await send_after_token(self.session, request, self.rate_limiter)
                    else:
                        response = await self.session.get(url, params=params, timeout=self.timeout)
                except httpx.TooManyRedirects as exc:
                    raise KrexConnectionError(
                        _redact_secrets(str(exc), secrets), url=url, params=_mask_params(params)
                    ) from None
                except httpx.HTTPError as exc:
                    error_type = (
                        KrexTimeoutError
                        if isinstance(exc, httpx.TimeoutException)
                        else KrexConnectionError
                    )
                    if attempt < attempts - 1:
                        await self._sleep_before_retry(attempt)
                        continue
                    raise error_type(
                        _redact_secrets(str(exc), secrets), url=url, params=_mask_params(params)
                    ) from None
                if 500 <= response.status_code < 600 and attempt < attempts - 1:
                    await self._sleep_before_retry(attempt)
                    continue
                return self._raise_for_response(response, provider=provider, params=params)
        except KrexError as exc:
            self.protect_error(exc)
            raise exc from None
        raise KrexServerError("request failed after retries", url=url, params=_mask_params(params))

    def _validate_auth(self, httpx: Any) -> None:
        if isinstance(self.session, httpx.AsyncClient):
            auth = self.session.auth
            if auth is not None and type(auth) not in {httpx.Auth, httpx.BasicAuth}:
                raise TypeError("session auth must not send additional authentication requests")

    async def _sleep_before_retry(self, attempt: int) -> None:
        if self.retry_backoff > 0:
            await asyncio.sleep(min(self.retry_backoff * (2**attempt), _MAX_BACKOFF_SECONDS))

    async def aclose(self) -> None:
        if not self._closed:
            self._closed = True
            if self._owns_session and self.session is not None:
                await self.session.aclose()

    async def __aenter__(self) -> KrexHttp:
        return self

    async def __aexit__(self, *_exc_info: Any) -> None:
        await self.aclose()

    def _raise_for_response(
        self,
        response: Any,
        *,
        provider: str,
        params: dict[str, Any],
    ) -> NormalizedPayload:
        status = int(response.status_code)
        masked_params = _mask_params(params)
        headers = _response_headers(response)
        secrets = (self.ex_api_key, self.go_api_key)
        body_preview = _redact_secrets(response.text, secrets)[:200]
        if status in (401, 403):
            self.last_response = _debug_response(status, headers, body_preview)
            raise KrexAuthError(
                f"HTTP {status}: {body_preview}",
                http_status=status,
                params=masked_params,
            )
        if status == 400:
            self.last_response = _debug_response(status, headers, body_preview)
            raise KrexBadRequestError(body_preview, http_status=status, params=masked_params)
        if status == 404:
            self.last_response = _debug_response(status, headers, body_preview)
            raise KrexBadRequestError(
                "endpoint not found",
                http_status=status,
                params=masked_params,
            )
        if status == 429:
            self.last_response = _debug_response(status, headers, body_preview)
            raise KrexQuotaExceededError(
                body_preview,
                http_status=status,
                params=masked_params,
            )
        if 500 <= status < 600:
            self.last_response = _debug_response(status, headers, body_preview)
            raise KrexServerError(
                f"HTTP {status}: {body_preview}",
                http_status=status,
                params=masked_params,
            )

        try:
            payload = response.json()
        except ValueError as exc:
            self.last_response = _debug_response(status, headers, body_preview)
            raise KrexParseError(
                f"JSON parse failure: {exc}",
                http_status=status,
                params=masked_params,
            ) from exc
        self.last_response = _debug_response(status, headers, _redact_payload(payload, secrets))
        if not isinstance(payload, dict):
            raise KrexParseError(
                "response JSON must be an object",
                response=payload,
                params=masked_params,
            )

        if provider == "go" or "response" in payload:
            return _normalize_go_payload(payload, params=masked_params)
        return _normalize_ex_payload(payload, params=masked_params)


def _normalize_ex_payload(payload: dict[str, Any], *, params: dict[str, Any]) -> NormalizedPayload:
    if "code" in payload:
        code = str(payload.get("code"))
    elif "resultCode" in payload:
        code = str(payload.get("resultCode"))
    else:
        code = "SUCCESS"
    message = str(payload.get("message") or payload.get("resultMsg") or "")
    if code not in {"SUCCESS", "INFO-000", "00"}:
        _raise_ex_code(code, message, payload, params)

    raw_items = _ex_items(payload)
    try:
        items = normalize_items(raw_items, "items")
    except TypeError as exc:
        raise KrexParseError(str(exc), response=payload, params=params) from exc
    try:
        page_no = to_int_or_none(payload.get("pageNo"))
        num_of_rows = to_int_or_none(payload.get("numOfRows"))
        total_count = to_int_or_none(_first_present(payload, "count", "totalCount"))
    except ValueError as exc:
        raise KrexParseError(str(exc), response=payload, params=params) from exc
    return NormalizedPayload(
        items=items,
        page_no=page_no,
        num_of_rows=num_of_rows,
        total_count=total_count,
        raw=payload,
    )


def _normalize_go_payload(payload: dict[str, Any], *, params: dict[str, Any]) -> NormalizedPayload:
    try:
        response = payload.get("response", payload)
        header = response["header"]
        body = response.get("body", {})
    except (KeyError, TypeError) as exc:
        raise KrexParseError(
            "data.go.kr response did not contain response.header",
            response=payload,
        ) from exc
    if not isinstance(header, dict) or not isinstance(body, dict):
        raise KrexParseError("data.go.kr header/body must be objects", response=payload)

    code = str(header.get("resultCode", ""))
    message = str(header.get("resultMsg", ""))
    if code != "00":
        _raise_go_code(code, message, payload, params)

    raw_items = body.get("items", [])
    if isinstance(raw_items, dict) and "item" in raw_items:
        raw_items = raw_items["item"]
    try:
        items = normalize_items(raw_items, "response.body.items")
    except TypeError as exc:
        raise KrexParseError(str(exc), response=payload, params=params) from exc
    try:
        page_no = to_int_or_none(body.get("pageNo"))
        num_of_rows = to_int_or_none(body.get("numOfRows"))
        total_count = to_int_or_none(body.get("totalCount"))
    except ValueError as exc:
        raise KrexParseError(str(exc), response=payload, params=params) from exc
    return NormalizedPayload(
        items=items,
        page_no=page_no,
        num_of_rows=num_of_rows,
        total_count=total_count,
        raw=payload,
    )


def _ex_items(payload: dict[str, Any]) -> Any:
    for key in ("list", "List", "data", "items", "item", "realTimeSMSList"):
        value = payload.get(key)
        if value is not None:
            return value
    metadata_keys = {"code", "message", "count", "pageNo", "numOfRows", "pageSize"}
    candidates = [
        value
        for key, value in payload.items()
        if key not in metadata_keys and isinstance(value, list)
    ]
    if len(candidates) > 1:
        raise KrexParseError(
            "ambiguous EX payload: multiple top-level list fields", response=payload
        )
    return candidates[0] if candidates else []


def _first_present(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = payload.get(key)
        if value is not None:
            return value
    return None


def _raise_ex_code(
    code: str,
    message: str,
    payload: dict[str, Any],
    params: dict[str, Any],
) -> None:
    text = f"data.ex.co.kr returned {code}: {message}"
    kwargs: dict[str, Any] = {"code": code, "response": payload, "params": params}
    if code in {"INVALID_KEY", "EXPIRED_KEY", "NO_REGISTERED_KEY"}:
        raise KrexAuthError(text, **kwargs)
    if code == "EXCEEDED_LIMIT":
        raise KrexQuotaExceededError(text, **kwargs)
    if code == "INVALID_REQUEST_PARAMETER":
        raise KrexMissingParameterError(text, **kwargs)
    if code == "INVALID_PARAMETER_VALUE":
        raise KrexInvalidParameterError(text, **kwargs)
    if code == "NO_DATA":
        raise KrexNotFoundError(text, **kwargs)
    if code in {"SERVICE_TIMEOUT", "SERVICE_UNAVAILABLE"}:
        raise KrexServiceUnavailableError(text, **kwargs)
    if code == "SYSTEM_ERROR":
        raise KrexServerError(text, **kwargs)
    raise KrexError(text, **kwargs)


def _raise_go_code(
    code: str,
    message: str,
    payload: dict[str, Any],
    params: dict[str, Any],
) -> None:
    text = f"data.go.kr returned {code}: {message}"
    kwargs: dict[str, Any] = {"code": code, "response": payload, "params": params}
    if code in {"01", "02", "04"}:
        raise KrexServerError(text, **kwargs)
    if code == "03":
        raise KrexNotFoundError(text, **kwargs)
    if code == "05":
        raise KrexServiceUnavailableError(text, **kwargs)
    if code == "10":
        raise KrexInvalidParameterError(text, **kwargs)
    if code == "11":
        raise KrexMissingParameterError(text, **kwargs)
    if code == "12":
        raise KrexBadRequestError(text, **kwargs)
    if code in {"20", "21", "30", "31", "32", "33"}:
        raise KrexAuthError(text, **kwargs)
    if code == "22":
        raise KrexQuotaExceededError(text, **kwargs)
    raise KrexError(text, **kwargs)


def _mask_value(value: str) -> str:
    return "<REDACTED>"


def _mask_params(params: dict[str, Any]) -> dict[str, Any]:
    masked = dict(params)
    for key in ("key", "serviceKey"):
        if key in masked:
            masked[key] = _mask_value(str(masked[key]))
    return masked


def _redact_secrets(text: str, secrets: tuple[str | None, ...]) -> str:
    variants = {
        value
        for secret in secrets
        if secret
        for value in (secret, quote(secret, safe=""), quote_plus(secret))
    }
    for value in sorted(variants, key=len, reverse=True):
        text = text.replace(value, "<REDACTED>")
    return text


def _redact_payload(value: Any, secrets: tuple[str | None, ...]) -> Any:
    if isinstance(value, dict):
        return {key: _redact_payload(item, secrets) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_payload(item, secrets) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_payload(item, secrets) for item in value)
    if isinstance(value, str):
        return _redact_secrets(value, secrets)
    return value


def normalize_api_key(value: str | None) -> str | None:
    """복사/붙여넣기 과정에서 섞인 모든 공백 문자를 제거합니다."""

    if value is None:
        return None
    normalized = "".join(str(value).split())
    return normalized or None


def _response_headers(response: Any) -> dict[str, str]:
    headers = getattr(response, "headers", {})
    if not headers:
        return {}
    return {str(key): str(value) for key, value in dict(headers).items()}


def _debug_response(status_code: int, headers: dict[str, str], body: Any) -> dict[str, Any]:
    return {"status_code": status_code, "headers": headers, "body": body}
