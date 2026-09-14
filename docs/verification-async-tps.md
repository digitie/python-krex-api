# 비동기·TPS 검증 결과

2026-09-14 기준. 독립 적대적 리뷰 2인 승인 후 live E2E를 실행했다.

- 오프라인: 106 passed, 14 subtests, coverage 92.02% (90% 기준).
- mypy 12개 파일, ruff, compileall 통과. CodeGraph sync 완료.
- 리뷰 A: 오류 코드 키 노출, 인증 흐름의 추가 송신, 토큰 대기 중 인증 변경을 수정하고 독립 재현 9개 및 회귀 11개 통과.
- 리뷰 B: API 인자·모델·선행 0·NO_DATA·날씨 탐색 의미 보존 확인. 문서 예제 19개 모의 실행 통과.
- live: **6 passed, 1 failed**. EX 조회와 디버그는 통과했다.
- 실패: `restarea.list_all(num_of_rows=1)`의 공공데이터포털 전국휴게소 표준데이터가 HTTP 403,
  `SERVICE_KEY_IS_NOT_REGISTERED_ERROR`, `returnReasonCode=30`을 반환했다.
  이 실패를 데이터 조회 성공으로 계산하지 않는다. 서비스키는 기록하지 않는다.

기존 동기 facade와 Async 접두사 별칭을 제거했고, 원본의 사용자 TPS 변경을 통합해
기본 5TPS 및 capacity=1을 유지했다. 공유 AsyncTokenBucket 주입으로 여러 클라이언트의
송신·재시도·리다이렉트·디버그 예산을 합산할 수 있다.

전국휴게소 표준데이터의 새 403은 사용자에게 보고했으며 별도 판단 전까지 머지를 보류한다.
