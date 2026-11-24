# DART 기업 식별 목록: 정상 조회 저장과 장애 시 마지막 정상 목록 사용

작성 2026-11-24 KST · 시작 커밋 `f16e103` (작업 트리 깨끗함)

## 확인한 원인

- 기존 기능: `dart_corporate_snapshot.use_corporate_snapshot`는 **앱에 동봉된 파일**
  (`stock_lab_core/data/dart_corporate_codes.json`)만 대체 목록으로 썼다. 실시간 조회에
  성공해도 그 결과를 저장하는 경로는 없었다. 수동 스크립트
  `scripts/refresh_dart_corporate_snapshot.py`만 파일을 갱신한다.
- 동봉 파일 `retrieved_at=2026-11-07T08:07Z`, 유효기간 7일 → 2026-11-14 만료.
- 같은 timeout 입력으로 재현: now=11-13이면 4,013건 사용, now=11-21이면 0건
  (`unavailable_or_expired`). 11-21 보고서 `3d4dd441`의 국내 31개 발행사 미연결은
  **DART 접속 실패(connect_timeout, 기존 재시도 포함 2회) + 이미 만료된 동봉 목록**이 겹친 결과다.
- 접속 실패 자체의 원인(DART 측 장애인지, Streamlit Cloud 망 문제인지)은 이 환경에서
  확인할 수 없었다. 이 작업 환경의 프록시가 opendart.fss.or.kr 연결을 막는다(403).
  사용자가 제공한 11-24 11:24 보고서(61)는 국내 공시 실적 6건을 보여 주므로 그 시점에는 실시간 조회가 정상이었다.
- 11-20 09:18 보고서(47)는 국내 공시 실적 행이 0건이다(동봉 목록은 이미 만료된 상태).

## 변경

- `dart_corporate_store.py` (신규): 주입된 Supabase 클라이언트로 `dart_corporate_code_snapshots`
  테이블의 출처별 한 행을 읽고 쓴다. 읽을 때 건수와 SHA-256을 대조하고, 맞지 않으면 쓰지 않는다.
  DB 예외 문구는 남기지 않는다(고정 코드만 사용).
- `dart_corporate_snapshot.py`:
  - 실시간 조회에 성공하면 기존과 같은 식별자 형식 검증을 거쳐 보관소에 저장한다
    (`persist_status`). 직전 정상 목록보다 10% 넘게 줄어든 목록은 잘린 응답으로 보고 덮어쓰지 않는다.
    같은 목록은 12시간 안에 다시 쓰지 않는다. 저장에 실패해도 실시간 결과는 그대로 쓴다.
  - 전송 계열 실패(connect/read timeout, transport)에서만 대체 목록을 쓴다. 보관소의 마지막 정상
    목록과 동봉 파일 가운데 **유효한 것 중 가장 최신**을 고른다. 7일 한도, 식별자 검증,
    인증·API 오류를 숨기지 않는 규칙은 그대로다.
  - 진단에 `snapshot_origin`, `snapshot_candidates`(origin별 valid/expired/absent/invalid/unavailable),
    `snapshot_status`를 추가했다. 기존 `mapping_source="official_snapshot"` 계약은 유지하므로
    정밀관측 식별 만료 검사, 공시 탐색의 유효기한 검사는 그대로 적용된다.
  - `snapshot_notice`: 저장 시각, 경과일, 유효기한을 표시하고 "기업 식별용 목록이며 재무제표·공시의
    최신성과는 별개", "저장 이후 신규 상장 기업은 식별되지 않을 수 있음"을 함께 적는다.
- `earnings_filing_sources.py`: 대체 목록에 없는 종목은 `dart_ticker_mapping_unavailable_in_snapshot`
  으로 구분한다. 추측 매핑이나 공시 요청은 하지 않는다. `snapshot_origin`을 발행사 진단에 싣는다.
- `earnings_pipeline.py`: 위 사유를 "DART 종목·회사 식별자 미등록 · 보관 목록 기준(저장 이후 신규 상장 가능)"으로 표시한다.
- `report_dart_earnings.py`, `report_reading.py`: 국내 실적 표 아래에 대체 목록을 쓴 경우에만 안내 한 줄을 넣는다.
- `app.py`: Supabase 클라이언트가 있으면 보관소를 연결한다. 재무 점검 표에 `기업코드 보관 상태`를 추가했다.
- `docs/20261124_dart_corporate_codes.sql`: 테이블 생성 SQL. **준비만 했고 실행하지 않았다.**
  실행 전에는 `persist_status=schema_unavailable`이 되고 기존 동작(동봉 파일만 사용)을 유지한다.

바꾸지 않은 것: 재시도 횟수(1회 추가), 요청 timeout 5초/8초, 공시 탐색 캐시 TTL 86400초,
실패 TTL 90초, 앱 캐시 1800초, 7일 유효기간, 식별자·실적 검증 기준, 점수·판정.

## 검증

- 수정 전: 관련 테스트 250건 통과 + 1건 실패. report 게이트 208건 통과(`report_os5l1bj8`, 39.1초).
- 수정 후: 관련 테스트 273건 통과 + 같은 1건 실패. report 게이트 208건 통과(`report_9h5or2_w`, 34.9초).
- 실패 1건 `test_dart_evidence_view::test_existing_parser_and_app_functions_preserved`는 수정 전
  커밋에서도 똑같이 실패한다. app.py의 모든 함수를 오래된 커밋 `5cadb203`과 비교하는 테스트라
  그 뒤 바뀐 함수들 때문에 실패한다. 이번 변경과 무관하며 테스트는 고치지 않았다.
- 신규 `tests/test_dart_corporate_store.py` 17건:
  정상 조회 저장, 같은 목록 재기록 생략, 잘린/잘못된 목록 거부, 보관소 장애 시에도 실시간 결과 유지,
  11-21 재현(동봉 목록 만료 + 보관소 없음), 인증·API 오류 비은닉, 마지막 정상 목록 복구와
  날짜·최신성 표시, 7일 한도 유지와 최신 출처 선택, 변조·접속 불가 행 미사용, 재시작 후 복구,
  신규 기업 미등록 명시(공시 요청 없음), 보고서 안내 줄.

## 남은 것

- Supabase에서 SQL을 실행해야 영구 저장이 작동한다.
- 운영 확인: 배포 후 실시간 성공 시 `persist_status=saved`가 기록되는지, 재부팅 후 접속 실패 때
  `snapshot_origin=persistent_last_success`가 쓰이는지 확인.
- 기존 동작으로 남은 한계: 공시 탐색은 대체 목록으로 만든 결과도 24시간 캐시하므로, DART가 그 사이
  회복돼도 다음 실시간 조회는 캐시 만료 뒤에 일어난다. 캐시 정책이라 이번에는 바꾸지 않았다.
- 실시간 성공 때 보관소 조회 1회(필요하면 저장 1회)가 늘어난다. 공시 탐색 기준 24시간에 한 번,
  앱 재무 점검 기준 30분에 한 번이다.
