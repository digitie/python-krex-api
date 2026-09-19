# 오류 코드와 비동기 오류 처리

매핑의 기준은 `src/krex/_http.py`와 `src/krex/exceptions.py`다.
공급자 응답은 HTTP 200이어도 본문의 오류 코드에 따라 실패할 수 있다.

## 공통 예외

모든 라이브러리 오류는 `KrexError`를 상속한다. 주요 하위 타입은 인증 오류
`KrexAuthError`, 요청 오류 `KrexBadRequestError`(필수/값 오류 포함),
호출 제한 `KrexQuotaExceededError`, 데이터 없음 `KrexNotFoundError`,
서버 오류 `KrexServerError`, 파싱 오류 `KrexParseError`,
네트워크 오류 `KrexNetworkError`(timeout/connection 포함), 설정 오류 `KrexConfigError`다.
`KrexServiceUnavailableError`는 서버 오류와 timeout 양쪽을 상속한다.

| 속성 | 타입 | 의미 |
|---|---|---|
| `code` | `str / None` | 공급자 코드. 알려진 키가 echo되면 마스킹한다. |
| `message` | `str` | 표시용 오류 설명 |
| `response` | `Any / None` | 가능한 경우 키를 마스킹한 오류 응답 |
| `url` | `str / None` | 가능한 경우 요청 URL |
| `params` | `dict / None` | 가능한 경우 키를 마스킹한 요청 인자 |
| `http_status` | `int / None` | HTTP 상태가 판별된 오류의 상태값 |
| `retry_after` | `int / None` | 선택 필드. 현재 HTTP 계층은 자동으로 채우지 않는다. |

## HTTP 상태와 재시도

| 조건 | 결과 |
|---|---|
| 400, 404 | `KrexBadRequestError` |
| 401, 403 | `KrexAuthError`, 재시도하지 않음 |
| 429 | `KrexQuotaExceededError`, 재시도하지 않음 |
| 5xx | 재시도 후 `KrexServerError` |
| HTTPX timeout | 재시도 후 `KrexTimeoutError` |
| 다른 HTTPX 네트워크/전송 오류 | 재시도 후 `KrexConnectionError` |
| 리다이렉트 상한 초과 | `KrexConnectionError`, 재시도하지 않음 |
| JSON 파싱/응답 구조/모델 변환 실패 | `KrexParseError` |
| 토큰 대기/본문 읽기 취소 | `asyncio.CancelledError`를 그대로 전달 |

기본 timeout은 10초, max_retries는 2이며 최초 요청을 포함하면 최대 3회다.
retry_backoff는 0.5초, 지수 증가 상한은 30초다. 각 시도·리다이렉트도 동일한
AsyncTokenBucket의 토큰을 소비한다. HTTP 200의 공급자 오류 코드는 자동 재시도하지 않는다.
`is_retryable` 속성은 제공하지 않는다. 외부 재시도 루프는 별도로 추가하지 않아도 된다.

```python
import asyncio
from krex import KrexClient
from krex.exceptions import KrexAuthError, KrexNetworkError, KrexQuotaExceededError


async def main() -> None:
    async with KrexClient.from_env(max_retries=2, retry_backoff=0.5) as client:
        try:
            page = await client.traffic.by_route(route_no="0010", time_unit="1")
            print(page.items)
        except KrexAuthError as exc:
            print("키와 서비스 권한을 확인하세요:", exc)
        except KrexQuotaExceededError as exc:
            print("요청 제한 응답:", exc)
        except KrexNetworkError as exc:
            print("재시도 후에도 연결하지 못했습니다:", exc)


asyncio.run(main())
```

## data.ex.co.kr 본문 코드

| 코드 | 예외 |
|---|---|
| SUCCESS, INFO-000, 00 | 정상 envelope 파싱 |
| INVALID_KEY, EXPIRED_KEY, NO_REGISTERED_KEY | `KrexAuthError` |
| EXCEEDED_LIMIT | `KrexQuotaExceededError` |
| INVALID_REQUEST_PARAMETER | `KrexMissingParameterError` |
| INVALID_PARAMETER_VALUE | `KrexInvalidParameterError` |
| NO_DATA | `KrexNotFoundError` |
| SERVICE_TIMEOUT, SERVICE_UNAVAILABLE | `KrexServiceUnavailableError` |
| SYSTEM_ERROR | `KrexServerError` |
| 기타 코드 | `KrexError` |

## data.go.kr 본문 코드

| response.header.resultCode | 예외 |
|---|---|
| 00 | 정상 envelope 파싱 |
| 01, 02, 04 | `KrexServerError` |
| 03 | `KrexNotFoundError` |
| 05 | `KrexServiceUnavailableError` |
| 10 | `KrexInvalidParameterError` |
| 11 | `KrexMissingParameterError` |
| 12 | `KrexBadRequestError` |
| 20, 21, 30, 31, 32, 33 | `KrexAuthError` |
| 22 | `KrexQuotaExceededError` |
| 기타 코드 | `KrexError` |

## 데이터 없음 처리

기본 `strict_no_data=True`는 공급자의 NO_DATA를 예외로 전달한다.
빈 Page를 받으려면 생성자에 `strict_no_data=False`를 명시한다.
`traffic.flow()`와 `traffic.flow_all()`의 명시적인 `count=0, list=[]`는 정상 빈 응답이다.
목록·건수 누락, 건수 불일치, 일부 행 파싱 실패는 `strict_no_data=False`에서도
`KrexParseError`로 거부한다. 빈 필터 결과나 범위 밖 로컬 페이지는 빈 `Page`다.
`latest_weather`는 과거 시간대를 찾는 목적에 맞게 NO_DATA인 시간대를 건너뛴다.

```python
import asyncio
from krex import KrexClient


async def main() -> None:
    async with KrexClient.from_env(strict_no_data=False) as client:
        page = await client.traffic.by_route(route_no="0010", time_unit="1")
        if not page.items:
            print("데이터 없음")


asyncio.run(main())
```

## 진단과 키 보호

키를 출력하지 말고 포털 종류와 설정 여부를 확인한다. EX와 공공포털은 각각
KEX_EX_API_KEY, DATA_GO_KR_SERVICE_KEY를 사용한다. 공공포털에는 디코딩된 키를 전달한다.
인자 검증은 요청 전에 수행한다. 원문으로 오류 분류와 모델 검증을 마친 뒤
알려진 키와 인코딩된 키를 예외·진단 출력에서 마스킹한다.

`debug_call`은 호출별 request/response/error를 제공한다. HTTP 200의
실시간 문자정보도 realTimeSMSList와 0 이상 count가 없으면 파싱 오류다.
공유 client의 전역 last-response 대신 DebugRun으로 현재 호출 결과를 확인한다.

```python
import asyncio
from krex import KrexClient, jsonable


async def main() -> None:
    async with KrexClient.from_env() as client:
        run = await client.debug_call("traffic.by_route", route_no="0010", time_unit="1")
        print(run.request)
        print(run.response)
        print(run.error)
        print(jsonable(run.parsed))


asyncio.run(main())
```

세션 주입과 TPS의 세부 계약은 [비동기 API와 공통 TPS](docs/async-tps.md)를 참고한다.
