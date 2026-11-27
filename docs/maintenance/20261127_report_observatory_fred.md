# 리포트에 관측실 FRED 지표 재사용 (2026-11-27, 우선순위 5번 첫 건)

## 문제
매크로 관측실은 FRED 8개 지표(금융스트레스 STLFSI4, 10Y-2Y T10Y2Y, M2 M2SL, 신규실업수당 ICSA,
연준 총자산 WALCL, 지준 WRESBAL, 역레포 RRPONTSYD, 재무부 일반계정 WTREGEN)를 보여 주지만
자동시황 리포트에는 이 값이 전달되지 않았다.

## 수정 (표시 전용)
- `report_dashboard.observatory_fred_observations`: 관측실과 같은 `macro_monitor.observation` 로더(캐시 15분,
  같은 키)로 8개를 병렬(4개) 조회. 실패·결측은 `미연결`로 남기고 0이나 추정으로 채우지 않는다.
- `report_context`: `measure("external_data", "observatory_fred")` 구간으로 소요 시간을 따로 기록.
- `report_reading`: 매크로 구역 국가 표 앞에 `유동성·연준 · 관측실 FRED 지표` 표
  (대상 | 수준 | 직전 관측 대비 | 관측일·주기 | 상태 | 출처)와 `연결 n/8 · 준비 x초` 문장.
- 점수·판정·시장방어 입력에는 넣지 않는다.

## 검증
- `tests/test_report_observatory_fred.py` 3개(관측일 유지·실패는 채우지 않음, 표가 리포트 커버리지 상태에 집계됨, 자료 없으면 표 없음).
- `check_refactor --scope report` 수정 전 208/0, 수정 후 208/0 (같은 venv).
- 클라우드는 FRED가 프록시 403이라 실제 값은 운영 리포트에서만 확인 가능. 운영 확인: HANDOFF 참조.
