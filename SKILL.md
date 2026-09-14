---
name: python-krex-api
description: data.ex.co.kr와 data.go.kr로 제공되는 한국도로공사 OpenAPI Python client를 구현, 확장, test, troubleshooting할 때 사용한다.
---

# SKILL — python-krex-api 에이전트 매뉴얼

> 이 파일은 당신(AI 에이전트)이 작업을 시작하기 전 반드시 읽어야 한다.
> 1회만 읽으면 30분 이상의 디버깅을 줄일 수 있다.

## 1. 정체성

이 프로젝트(GitHub/PyPI 이름 `python-krex-api`, import 패키지 이름 `krex`)는 한국도로공사 OpenAPI (`data.ex.co.kr`, `data.go.kr`)를 Python 환경에서 쉽게 사용할 수 있도록 제공하는 **OpenAPI 클라이언트 라이브러리**다.

공개 package import 이름은 `krex`, distribution 이름은 `python-krex-api`다.
도메인 시각화나 Streamlit 등의 디버그 UI 도구는 배포 패키지 코어 의존성에서 철저히 제외하며, 소비자 앱이 해당 역할을 담당하도록 설계되었다.

### 식별자 매핑

| 항목 | 값 |
|------|----|
| GitHub 저장소 | `python-krex-api` |
| PyPI 패키지 | `python-krex-api` |
| import | `import krex` / `from krex import KrexClient` |
| 데이터 소스 | 한국도로공사 OpenAPI (`data.ex.co.kr`, `data.go.kr`) |
| API 인증 키 변수 | `KEX_EX_API_KEY`, `DATA_GO_KR_SERVICE_KEY` |

## 2. 빠른 시작

```bash
cd F:\dev\python-krex-api
python -m compileall src/krex tests
python -m pytest
python -m mypy src/krex
ruff check .
```

git 관련 작업은 Windows용 `git.exe`를 사용한다. WSL에서 작업 중이어도 `"/mnt/c/Program Files/Git/cmd/git.exe"` 호출을 기본으로 삼는다.

실제 API 호출을 통한 검증을 진행할 경우:
```powershell
$env:KEX_LIVE="1"
python -m pytest -m live -vv
```

에이전트 작업은 고정 worktree에서 진행한다. ChatGPT Codex는 `F:\dev\python-krex-api-codex`, Claude Code는 `F:\dev\python-krex-api-claude`, Google Antigravity는 `F:\dev\python-krex-api-antigravity`를 사용한다. worktree마다 한 번만 `codegraph init -i`를 실행하고, 작업 시작마다 `git fetch` 후 새 브랜치를 만들고 `codegraph sync`를 실행한다.

## 3. 디렉토리 지도

```
src/
  krex/
    _http.py       — transport, retry, API envelope/error mapping
    _convert.py    — 응답 경계의 작은 변환 helper
    codes.py       — enum과 code label (StrEnum 선호)
    models.py      — 공개 Pydantic 반환 model (`KrexModel` 기반)
    client.py      — 고수준 endpoint namespace와 parsing
    catalog.py     — 구현 API catalog, dataset 이름, service-key 신청 URL
    debug.py       — DebugRun, JSON 변환, redaction, fixture 저장
    exceptions.py  — 공통 예외 및 에러 매핑
tests/             — Pytest 기반 테스트 코드 및 JSON fixture들
pyproject.toml     — 패키지 메타데이터 및 의존성 설정
API_COVERAGE.md    — 구현 여부와 live verification 상태의 기준 문서
endpoints.md       — 구현된 각 API의 path 및 파라미터 상세
codes.md           — 공통 코드 테이블 및 Enum 설명 문서
error-codes.md     — API 에러 코드 분석 문서
```

## 4. 절대 하지 말 것 (DO NOT)

1. **`main` 직접 푸시 금지**: 반드시 feature 브랜치를 만들어 PR 후 머지하는 방식을 따른다.
2. **API Key 평문 커밋 금지**: `data.ex.co.kr`에는 `KEX_EX_API_KEY`, `data.go.kr`에는 `DATA_GO_KR_SERVICE_KEY` 환경 변수를 사용하며, `.env` 파일은 절대 커밋하지 않는다.
3. **Unit Test에서 network 직접 호출 금지**: Fake session 또는 JSON fixture를 구성하여 Mocking 검증해야 한다.
4. **Stable 의미가 있는 반환값을 raw string으로 노출 금지**: raw string보다 Pydantic 모델이나 Enum 형식으로 제공한다.
5. **모호한 raw 주소 데이터에서 법정동 코드 임의 추측 금지**: 주소 데이터는 원문 그대로 문자열로 유지한다.
6. **코드 문자열의 Leading zero 제거 금지**: `routeNo="0010"`이나 `unitCode="101"` 같은 office/branch 코드는 앞에 붙은 0을 절대 numeric으로 변환하지 않고 문자열 타입을 유지한다.
7. **테스트를 실시간 API 데이터 상태에 의존하게 만들기 금지**: local JSON fixture 파일을 적극 활용하여 오프라인에서도 재현 가능하게 검증한다.
8. **임시/캐시 파일 커밋 금지**: `.pytest_cache`, `.mypy_cache`, `.ruff_cache`, `.coverage`, `.venv` 폴더는 커밋하지 않는다.
9. **`strict_no_data=False` 가드가 없는 한 `NO_DATA` 응답 성공 처리 금지**: 명시적 에러 처리를 준수한다.
10. **`data.ex.co.kr` 응답이 항상 `list`라고 가정 금지**: Korean public API는 단일 item일 때 `dict`, 다중 item일 때 `list`를 반환할 수 있으므로 이에 대한 정규화 처리가 필수적이다.
11. **API Key가 repr 표현식이나 실패 로그에 노출되게 만들기 금지**: `KrexClient` 인스턴스 출력 또는 에러 문자열 조립 시 API Key가 절대 유출되지 않게 마스킹해야 한다.
12. **Windows에서 `rg.exe`가 Access Denied 시 무한 반복 금지**: 즉시 PowerShell `Get-ChildItem`과 `Select-String -Encoding UTF8` 백업 명령어를 활용한다.
13. **`.codegraph/` 커밋 금지**: CodeGraph 인덱스는 worktree 로컬 산출물이다. 이미 초기화된 worktree에서는 `codegraph init` 재실행 대신 `codegraph sync`를 사용한다.
14. **WSL 기본 `git`로 worktree를 억지로 다루지 말 것**: 이 저장소는 Windows worktree 메타데이터를 사용할 수 있으므로 git 명령은 Windows용 `git.exe`로 실행한다.

## 5. 자주 묻는 작업

| 작업 | 시작 파일 |
|------|-----------|
| 새 API 엔드포인트 추가 | `src/krex/client.py`에 API 호출 메서드 추가 → `src/krex/models.py`에 반환 Pydantic 모델 정의 → `src/krex/catalog.py`에 메타데이터 등록 |
| 새로운 코드 및 Enum 추가 | `src/krex/codes.py`에 StrEnum 정의 → `codes.md`에 설명 보충 |
| 엔드포인트 응답 변환 추가 | `src/krex/_convert.py`에 타입 파싱 및 포맷팅 헬퍼 메서드 추가 |
| 에러 처리 세분화 | `src/krex/_http.py` 혹은 `exceptions.py`에서 에러 매핑 확장 |
| 오프라인 테스트용 Fixture 추가 | `tests/` 아래 JSON fixture 추가 → `tests/` 에 해당 엔드포인트를 호출하는 Mocking test 구현 |

## 6. 도메인 어휘

| 약어 / 용어 | 의미 |
|------|------|
| KEX / 도로공사 | 한국도로공사 (`data.ex.co.kr` 포털) |
| public / 공공포털 | 공공데이터 포털 (`data.go.kr` 포털) |
| KrexModel | 이 라이브러리 전체에서 사용하는 Pydantic base model |
| StrEnum | Python `enum.StrEnum` 스타일의 문자열 매핑 타입 |
| payload normalization | 단일 `dict` 또는 다중 `list` 응답 형태를 안정된 하나의 리스트 구조로 정규화하는 과정 |
| `KEX_EX_API_KEY` | `data.ex.co.kr` 용 인증 Key |
| `DATA_GO_KR_SERVICE_KEY` | `data.go.kr` 용 인증 Service Key |

## 7. 작업 후 체크리스트

- [ ] `python -m compileall src/krex tests` 통과
- [ ] `python -m pytest` 통과
- [ ] `python -m mypy src/krex` 통과 (mypy가 설치된 환경인 경우)
- [ ] `ruff check .` 통과 (ruff가 설치된 환경인 경우)
- [ ] `README.md` 사용법 추가 완료 (신규 퍼블릭 API인 경우)
- [ ] `endpoints.md` 상세 명세 갱신 완료
- [ ] `API_COVERAGE.md` 지원 현황 및 검증 여부 상태 업데이트 완료
- [ ] `codes.md` 공통 코드 정보 업데이트 완료
- [ ] `error-codes.md` 에러 핸들링 관련 정보 업데이트 완료
- [ ] 민감한 API Key 정보가 코드, fixture, 커밋 로그에 절대 유출되지 않았는지 더블 체크 완료


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


사용 예제: [docs/async-tps.md](docs/async-tps.md).
