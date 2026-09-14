# 비동기 API와 공통 요청 속도 제어

## 비동기 호출과 공통 TPS

`KrexClient`와 모든 네트워크 서비스 메서드는 native async다. 조회와 디버그에는
`await`, 세션 관리에는 `async with` 또는 `await client.aclose()`를 사용한다.
동기 HTTP bridge, Async 접두사 클라이언트와 aio/adebug_call 별칭은 제거했다.
`reference.routes`, `reference.common_codes`, `reference.api_catalog`, 파싱과 코드표,
fixture 저장 등 로컬 유틸리티는 일반 함수다. 기존 서비스 인자·모델·선행 0 코드는 유지한다.

기존 TPS 변경의 기본값을 보존한다: `max_rps=5.0`, 버킷 `capacity=1`이다.
초기 버스트 없이 송신 사이에 최소 1/max_rps 간격을 둔다. 모든 서비스는 같은 버킷을
공유하고 각 재시도·리다이렉트·debug·latest_weather의 시간대 조회에도 토큰을 소비한다.

다른 라이브러리와 같은 구현의 `AsyncTokenBucket`을 `rate_limiter=`에 주입하면
여러 클라이언트가 요청 예산을 합산한다. 주입한 버킷이 max_rps보다 우선한다.
공통 버킷 클래스 자체의 기본 capacity는 max(1, max_rps)로 초기 burst를 허용하므로
Krex의 기본 간격을 유지하는 공유 버킷도 **capacity=1을 명시**한다.
버킷은 한 이벤트 루프에서 사용한다. 대기 취소는 토큰을 소비하지 않고 다음 대기자를 진행시킨다.

401/403/429는 즉시 실패한다. 5xx와 HTTPX 네트워크 오류는 기존 backoff를 유지하되
각 시도마다 새 토큰을 얻는다. 인자 검증 실패와 로컬 코드 조회는 토큰을 쓰지 않는다.
HTTPX 리다이렉트는 계측한다. Digest/custom Auth처럼 내부 추가 송신이 가능한 인증 세션은
첫 전송 전에 거부한다. 인증 없는 세션과 HTTPX 기본 BasicAuth를 지원한다. 사용자 정의
transport 내부의 연결 재시도는 라이브러리 밖의 동작이다.

내부 HTTP 세션은 첫 요청에서 생성하고 클라이언트 종료 시 닫는다. session에 주입한
비동기 세션은 호출자가 닫는다. 동기 get을 제공하는 세션은 거부한다.
디버그 기록은 ContextVar로 작업마다 격리하며 성공·실패·취소 뒤 복구한다.
원문으로 오류 분류·모델 파싱을 마친 후 예외와 진단 출력의 키를 마스킹한다.

```python
import asyncio
from krex import AsyncTokenBucket, KrexClient


async def main() -> None:
    bucket = AsyncTokenBucket(5, capacity=1)
    async with KrexClient.from_env(rate_limiter=bucket) as client:
        page = await client.restarea.route_facilities(num_of_rows=1)
        print(page.items)


asyncio.run(main())
```
