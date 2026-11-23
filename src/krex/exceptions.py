"""python-krex-api 예외 계층."""

from __future__ import annotations

from typing import Any


class KrexError(Exception):
    """모든 python-krex-api 예외의 공통 기반 클래스."""

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        response: Any | None = None,
        url: str | None = None,
        params: dict[str, Any] | None = None,
        http_status: int | None = None,
        retry_after: int | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.response = response
        self.url = url
        self.params = params
        self.http_status = http_status
        self.retry_after = retry_after


class KrexAuthError(KrexError):
    """API 키가 없거나, 잘못됐거나, 만료됐거나, 권한이 없을 때 발생합니다."""


class KrexQuotaExceededError(KrexError):
    """API가 호출 한도 초과를 보고할 때 발생합니다."""


class KrexBadRequestError(KrexError):
    """요청 형식이 잘못됐거나 거부됐을 때 발생합니다."""


class KrexMissingParameterError(KrexBadRequestError):
    """제공자가 필수 파라미터 누락을 보고할 때 발생합니다."""


class KrexInvalidParameterError(KrexBadRequestError):
    """로컬 또는 원격 파라미터 값이 유효하지 않을 때 발생합니다."""


class KrexNotFoundError(KrexError):
    """제공자가 조건에 맞는 데이터가 없다고 보고할 때 발생합니다."""


class KrexServerError(KrexError):
    """제공자 서버 또는 게이트웨이 장애일 때 발생합니다."""


class KrexParseError(KrexError):
    """응답을 예상한 형태로 파싱할 수 없을 때 발생합니다."""


class KrexPartialParseError(KrexParseError):
    """완결 목록 일부 행만 파싱할 수 없을 때 발생합니다(기본 계약은 여전히 실패).

    `KrexParseError`의 하위 클래스라 기존 소비자의 `except KrexParseError`는 그대로다.
    무효 행을 격리해 유효 행만 쓰기로 한 소비자만 이 예외를 잡아 `items`(파싱된 행,
    원문 순서)와 `received_rows`/`parsed_rows`/`invalid_rows`를 읽는다. 무효 행의 값은
    싣지 않는다(원문 전체는 기존처럼 `response`). 같은 응답을 다시 요청해도 결과가
    바뀌지 않는 결정적 오류이므로 재호출 근거로 쓰지 않는다.
    """

    def __init__(
        self,
        message: str,
        *,
        items: tuple[Any, ...],
        received_rows: int,
        **kwargs: Any,
    ) -> None:
        super().__init__(message, **kwargs)
        self.items = items
        self.received_rows = received_rows
        self.parsed_rows = len(items)
        self.invalid_rows = received_rows - len(items)


class KrexNetworkError(KrexError):
    """네트워크 계층 장애일 때 발생합니다."""


class KrexTimeoutError(KrexNetworkError):
    """요청 시간이 초과됐을 때 발생합니다."""


class KrexServiceUnavailableError(KrexServerError, KrexTimeoutError):
    """제공자 서비스를 일시적으로 사용할 수 없을 때 발생합니다."""


class KrexConnectionError(KrexNetworkError):
    """연결을 만들 수 없을 때 발생합니다."""


class KrexConfigError(KrexError):
    """클라이언트에 필요한 로컬 설정이 없을 때 발생합니다."""
