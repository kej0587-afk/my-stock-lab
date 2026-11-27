# SOXL·GOOGL 단축장 애프터 운영 확인

## 범위와 재기동
- 2026-11-28 06:08~06:11 KST, 공식 등록된 03~07KST 애프터 구간에서 확인.
- main99bad333/작업트리 일치·미커밋 없음. 운영 첫 화면은 dart_corporate_store import 중 KeyError.
  Cloud 관리 메뉴에서 직접 Reboot 후 정상 기동. 전체 서버 로그가 없으므로 오류 근본 원인은 미확정.
- 두 종목 완료 검토ZIP의 base_commit=99bad333, restart_required=False, stale_modules=[].
  운영 코드 변경/재설치 없이 재기동으로 복구됐으며 SOXS 프로필 수정은 이번 범위에 포함하지 않았다.

## 공급처 → 선택 → 정밀관측소
통화 USD, 시각은 모두 11/28 KST. 직전 정규장 종가일은 미국 11/27.

| 종목 | 정규장 종가 | 종가 체결 | 애프터 가격 | 종가 대비 | 애프터 체결 | 공급처 조회 |
|---|---:|---|---:|---:|---|---|
| GOOGL | 274.96 | 03:00:01 | 275.8889 (표시275.89) | +0.34% | 06:09:15 | 06:09:43.401 |
| SOXL | 36.57 | 03:00:01 | 35.89 | −1.86% | 06:09:44 | 06:10:09.097 |

- 운영 패널의 시세 연결 검토 JSON을 다운로드. 각각 HTTP200, 조회→체결 시각 차이는 약28초/25초.
- raw regularMarketPrice/Time과 regular 선택값, raw postMarketPrice/Time과 extended 선택값이 일치.
  등락률은 post/regular−1로 재계산해 일치. 현재 세션 체결이므로 이전 애프터/정규장 값 대체가 아님.
- UI에는 종가·종가 체결시각, 애프터 가격·등락·체결시각, 공급처 조회시각이 각각 표시됐다.
  cache성공60초/실패15초 유지. 이번 UI 후속 조회는 캐시 적중 횟수 측정 실험이 아니다.
- 계좌 원본을 포함한 ZIP과 응답 JSON은 개인 Downloads에만 보존. Git에 올리지 않음.

## 브리핑은 동일 응답 재생만
이 입력에서 SOXL/GOOGL은 자동시황 조회 범위 밖이다. 관심/보유목록을 바꾸거나 조회 범위를 늘리지 않았다.
다운로드한 provider_fields를 해당 checked_at으로 quote_audit/quote_evidence/extended_quote_text에 재생했다.
두 audit 전체 동등성 및 가격·시각·종가대비 등락 assertion 통과.

| 종목 | 재생 문장의 가격 | 11/25 종가 대비 누적 | 11/27 종가 대비 마감 후 | 비교 종가 |
|---|---:|---:|---:|---:|
| SOXL | 35.89 | +12.09% | −1.86% | 36.57 |
| GOOGL | 275.89 | +1.02% | +0.34% | 274.96 |

누적 등락과 마감 후 등락은 비교 기준이 다르며 모순이 아니다. 두 문장 모두 Yahoo/체결06:09KST/기준일 표시.
이 결과는 새 자동시황 전체 실행이나 운영 브리핑에 두 종목이 실제 등장한 검증이 아니다.

## 기존 판정 입력과의 구분 — 남은 설계 제한
- 원본 일봉(ohlcv_01)의 11/27 Close는 SOXL36.5699997, GOOGL274.9599915로 정규장 종가와 일치.
- 별도 기존 scalar 시세 경로는 cur_p SOXL35.899/GOOGL275.89를 사용한다. 패널과 조회시점·반올림이
  달라 SOXL35.89와 소폭 다르며, 패널의 원응답이 종가로 잘못 선택된 현상은 아니다.
- apply_live_price_to_ohlcv / apply_live_price_with_indicators 기존 동작으로 계산·차트 복사본
  ohlcv_02/03의 Close가 위 scalar로 바뀌고 LiveQuoteOnly=True, Volume=결측,
  quote_date_status=calendar_unverified가 남는다. 원본 일봉과 주·월봉 종가는 보존된다.
- 따라서 패널 자체의 quote_evidence 결과가 판정에 전달되지 않는 것과,
  **다른 기존 경로의 시간외 scalar가 일부 지표·판정 입력에 쓰이는 것**을 구분해야 한다.
  '시간외 가격이 어떤 판정/차트에도 반영되지 않는다'는 전면 분리 완료 주장은 하지 않는다.
  이 흐름/문구의 정합성은 후속 설계 점검 후보다. 이번에 기존 판정 입력을 변경하지 않았다.
- 운영 SOXL 판정 LEVERAGED_WATCH_NO_POSITION, 게이트 방어우선/레버리지 시장방어 확인.
  GOOGL QUALITY_RECOVERY_WATCH. 고정 입력 전후 판정 비교 실험이 아니라 현행 운영 관측이다.

## 검증·다음 한 건
- tests/test_extended_quote_sessions_audit.py, test_leveraged_quote_view.py,
  test_quote_evidence_cache.py: **108통과 / 0실패 / 6.83초**.
- 휴장/단축장 경계·동가 신규체결·지연·cache시각 보존은 테스트, 이번 운영은 실제 애프터 두 종목.
  전체 suite/전체 자동시황/모든 차트 영역은 재실행하지 않았다. 코드·TTL·점수·방어·월적립·L3 불변.
- 다음 한 건: SOXS 상품명 fallback이 SOXL 회복 프로필로 연결되는 오류만 차단.
  기존 시장방어/L3를 풀지 않고 SOXL 정상 경로·SOXS 미보유 보류 회귀를 확인한다.
