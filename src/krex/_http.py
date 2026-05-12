"""한국도로공사 API용 HTTP 헬퍼."""

from __future__ import annotations

from dataclasses import dataclass, field
from time import sleep
from typing import Any

from ._convert import normalize_items, to_int_or_none
from .exceptions import (
    KexAuthError,
    KexBadRequestError,
    KexConfigError,
    KexConnectionError,
    KexError,
    KexInvalidParameterError,
    KexMissingParameterError,
    KexNetworkError,
    KexNotFoundError,
    KexParseError,
    KexQuotaExceededError,
    KexServerError,
    KexServiceUnavailableError,
    KexTimeoutError,
)


def _load_requests() -> Any:
    try:
        import requests
    except ModuleNotFoundError as exc:
        raise KexConfigError("requests is required; install python-krex-api dependencies") from exc
    return requests


def _new_session() -> Any:
    return _load_requests().Session()


@dataclass(frozen=True, slots=True)
class NormalizedPayload:
    items: list[dict[str, Any]]
    page_no: int | None
    num_of_rows: int | None
    total_count: int | None
    raw: dict[str, Any]


@dataclass(slots=True)
class KexHttp:
    ex_api_key: str | None = field(default=None, repr=False)
    go_api_key: str | None = field(default=None, repr=False)
    timeout: float = 10.0
    max_retries: int = 2
    retry_backoff: float = 0.5
    session: Any = field(default_factory=_new_session, repr=False)
    ex_base_url: str = "https://data.ex.co.kr"

    def __post_init__(self) -> None:
        if self.session is None:
            self.session = _new_session()

    def get_ex(self, path: str, params: dict[str, Any] | None = None) -> NormalizedPayload:
        if not self.ex_api_key:
            raise KexAuthError("KEX_EX_API_KEY is not set and ex_api_key was not provided")
        query = {"key": self.ex_api_key, "type": "json"}
        if params:
            query.update(params)
        url = f"{self.ex_base_url.rstrip('/')}/{path.lstrip('/')}"
        return self._get(url, query, provider="ex")

    def get_go(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        *,
        standard: bool = False,
    ) -> NormalizedPayload:
        if not self.go_api_key:
            raise KexAuthError("KEX_GO_API_KEY is not set and go_api_key was not provided")
        query = {"serviceKey": self.go_api_key}
        query["type" if standard else "_type"] = "json"
        if params:
            query.update(params)
        return self._get(url, query, provider="go")

    def _get(self, url: str, params: dict[str, Any], *, provider: str) -> NormalizedPayload:
        requests = _load_requests()
        attempts = max(0, self.max_retries) + 1
        last_error: KexNetworkError | None = None

        for attempt in range(attempts):
            try:
                response = self.session.get(url, params=params, timeout=self.timeout)
            except requests.Timeout as exc:
                last_error = KexTimeoutError(str(exc), url=url, params=_mask_params(params))
                if attempt < attempts - 1:
                    self._sleep_before_retry(attempt)
                    continue
                raise last_error from exc
            except requests.ConnectionError as exc:
                last_error = KexConnectionError(str(exc), url=url, params=_mask_params(params))
                if attempt < attempts - 1:
                    self._sleep_before_retry(attempt)
                    continue
                raise last_error from exc

            if 500 <= response.status_code < 600 and attempt < attempts - 1:
                self._sleep_before_retry(attempt)
                continue

            return self._raise_for_response(response, provider=provider, params=params)

        if last_error is not None:
            raise last_error
        raise KexServerError("request failed after retries", url=url, params=_mask_params(params))

    def _sleep_before_retry(self, attempt: int) -> None:
        if self.retry_backoff > 0:
            sleep(self.retry_backoff * (2**attempt))

    def _raise_for_response(
        self,
        response: Any,
        *,
        provider: str,
        params: dict[str, Any],
    ) -> NormalizedPayload:
        status = int(response.status_code)
        masked_params = _mask_params(params)
        if status in (401, 403):
            raise KexAuthError(
                f"HTTP {status}: {response.text[:200]}",
                http_status=status,
                params=masked_params,
            )
        if status == 400:
            raise KexBadRequestError(response.text[:200], http_status=status, params=masked_params)
        if status == 404:
            raise KexBadRequestError("endpoint not found", http_status=status, params=masked_params)
        if status == 429:
            raise KexQuotaExceededError(
                response.text[:200],
                http_status=status,
                params=masked_params,
            )
        if 500 <= status < 600:
            raise KexServerError(
                f"HTTP {status}: {response.text[:200]}",
                http_status=status,
                params=masked_params,
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise KexParseError(
                f"JSON parse failure: {exc}",
                http_status=status,
                params=masked_params,
            ) from exc
        if not isinstance(payload, dict):
            raise KexParseError(
                "response JSON must be an object",
                response=payload,
                params=masked_params,
            )

        if provider == "go" or "response" in payload:
            return _normalize_go_payload(payload, params=masked_params)
        return _normalize_ex_payload(payload, params=masked_params)


def _normalize_ex_payload(payload: dict[str, Any], *, params: dict[str, Any]) -> NormalizedPayload:
    code = str(payload.get("code") or payload.get("resultCode") or "SUCCESS")
    message = str(payload.get("message") or payload.get("resultMsg") or "")
    if code not in {"SUCCESS", "INFO-000", "00"}:
        _raise_ex_code(code, message, payload, params)

    raw_items = _ex_items(payload)
    try:
        items = normalize_items(raw_items, "items")
    except TypeError as exc:
        raise KexParseError(str(exc), response=payload, params=params) from exc
    return NormalizedPayload(
        items=items,
        page_no=to_int_or_none(payload.get("pageNo")),
        num_of_rows=to_int_or_none(payload.get("numOfRows")),
        total_count=to_int_or_none(_first_present(payload, "count", "totalCount")),
        raw=payload,
    )


def _normalize_go_payload(payload: dict[str, Any], *, params: dict[str, Any]) -> NormalizedPayload:
    try:
        response = payload["response"]
        header = response["header"]
        body = response.get("body", {})
    except (KeyError, TypeError) as exc:
        raise KexParseError(
            "data.go.kr response did not contain response.header",
            response=payload,
        ) from exc
    if not isinstance(header, dict) or not isinstance(body, dict):
        raise KexParseError("data.go.kr header/body must be objects", response=payload)

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
        raise KexParseError(str(exc), response=payload, params=params) from exc
    return NormalizedPayload(
        items=items,
        page_no=to_int_or_none(body.get("pageNo")),
        num_of_rows=to_int_or_none(body.get("numOfRows")),
        total_count=to_int_or_none(body.get("totalCount")),
        raw=payload,
    )


def _ex_items(payload: dict[str, Any]) -> Any:
    for key in ("list", "List", "data", "items", "item"):
        if key in payload:
            return payload[key]
    for key, value in payload.items():
        metadata_keys = {"code", "message", "count", "pageNo", "numOfRows", "pageSize"}
        if key not in metadata_keys and isinstance(value, list):
            return value
    return []


def _first_present(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload:
            return payload[key]
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
        raise KexAuthError(text, **kwargs)
    if code == "EXCEEDED_LIMIT":
        raise KexQuotaExceededError(text, **kwargs)
    if code == "INVALID_REQUEST_PARAMETER":
        raise KexMissingParameterError(text, **kwargs)
    if code == "INVALID_PARAMETER_VALUE":
        raise KexInvalidParameterError(text, **kwargs)
    if code == "NO_DATA":
        raise KexNotFoundError(text, **kwargs)
    if code in {"SERVICE_TIMEOUT", "SERVICE_UNAVAILABLE"}:
        raise KexServiceUnavailableError(text, **kwargs)
    if code == "SYSTEM_ERROR":
        raise KexServerError(text, **kwargs)
    raise KexError(text, **kwargs)


def _raise_go_code(
    code: str,
    message: str,
    payload: dict[str, Any],
    params: dict[str, Any],
) -> None:
    text = f"data.go.kr returned {code}: {message}"
    kwargs: dict[str, Any] = {"code": code, "response": payload, "params": params}
    if code in {"01", "02", "04"}:
        raise KexServerError(text, **kwargs)
    if code == "03":
        raise KexNotFoundError(text, **kwargs)
    if code == "05":
        raise KexServiceUnavailableError(text, **kwargs)
    if code == "10":
        raise KexInvalidParameterError(text, **kwargs)
    if code == "11":
        raise KexMissingParameterError(text, **kwargs)
    if code == "12":
        raise KexBadRequestError(text, **kwargs)
    if code in {"20", "21", "30", "31", "32", "33"}:
        raise KexAuthError(text, **kwargs)
    if code == "22":
        raise KexQuotaExceededError(text, **kwargs)
    raise KexError(text, **kwargs)


def _mask_params(params: dict[str, Any]) -> dict[str, Any]:
    masked = dict(params)
    for key in ("key", "serviceKey"):
        if key in masked:
            value = str(masked[key])
            masked[key] = value[:4] + "..." if len(value) > 4 else "***"
    return masked
