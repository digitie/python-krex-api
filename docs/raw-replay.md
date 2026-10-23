# RestAreaWeather 원문 재해석

```python
from krex import parse_rest_area_weather

weather = parse_rest_area_weather(saved_row)
```

`row`는 휴게소 기상 provider 단일 행인 `dict[str, Any]`다. 원문 raw와 선행0 코드,
sdate/stdHour의 KST 시각, -99 이하 결측·좌표 변환을 기존대로 유지한다.
잘못된 필수값·날짜/시각은 로컬 행 재해석에서 기존처럼 `ValueError`를 낼 수 있다.
HTTP 페이지 파서는 일부 행이 실패해도 정상 행이 하나 이상 있으면 실패 행을 제외한
`Page`를 반환한다. 모든 행이 실패하고 첫 행 오류가 있을 때만 `KrexParseError`로
포장한다. 빈 페이지는 기존처럼 빈 `Page`다. 이 동작은 공개 함수 추가 전후에 동일하다.

## 원문 재해석의 신뢰 경계

이 API는 이미 확보한 provider record를 같은 SDK DTO로 다시 해석하는 로컬 함수다.
네트워크·인증키·현재 시각·원천 재조회 없이 기존 파서와 같은 변환을 사용한다.
HTTP header/resultCode, 전체 items 형태·byte/count 상한, 전국 집합의 완결성·신선도는
이 단일 행/장소만으로 검증하지 않는다. 호출자는 원문 확보 때의 응답 검증·출처·수집 시각과
대상 identity를 따로 보존해야 하며, 빈 결과를 전국 정상0건의 근거로 사용하면 안 된다.
