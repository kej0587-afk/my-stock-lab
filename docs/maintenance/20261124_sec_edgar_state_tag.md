# #8 SEC 발행사 이름 대조: EDGAR 주 표기 (2026-11-24)

## 문제

AMAT 실적 발표문이 `release_issuer_mismatch`로 보류됐다. SEC 제출 목록의 회사명은 "APPLIED MATERIALS INC /DE"이다.
"/DE"는 EDGAR가 붙이는 설립 주(델라웨어) 표기이고 회사명의 일부가 아니다. 기존 규칙은 이 꼬리표를 지우지 않아서,
"applied materials de"를 제목에서 찾다가 실패했다.

## 결정과 변경

사용자가 2026-11-24 15:58 KST에 "주 표기만 빼고 대조(권장)"를 선택했다.
- `earnings_filing_evidence.parse_sec_release`: 이름 끝의 대문자 슬래시 표기(`/DE`, `/DE/`, `/NEW/`, 2~4자, 여러 개 가능)만 지운 뒤,
  기존처럼 법인 접미사(Inc 등)를 지우고 남은 이름 전체가 제목에 단어 경계로 있어야 통과한다.
- 이름 중간의 표기, 소문자 표기, 다른 회사명, 이름에 단어가 더 붙은 경우는 그대로 불일치로 남는다.
- 기존 테스트 `test_legal_suffix_is_not_silently_removed_without_verified_alias`는 이 결정으로 기대가 바뀌어
  통과 3가지(`/DE`, `/DE/`, `/NEW/`)와 거절 4가지(다른 회사명, 중간 표기, 단어 추가, 소문자)로 나눴다.
- 날짜·분기·수치 검증과 점수·판정은 바꾸지 않았다. AAPL은 발표일(dateline) 미확인으로 계속 보류된다.

## 확인

- `tests/test_earnings_release_refusals.py` 19 통과.
- 실적·DART·SEC 테스트 829개 중 824 통과. 실패 5건은 main에서도 똑같이 실패한다(`test_dart_evidence_view`, SEC 검토 화면 4건).
- report 게이트 208 통과(`report_5kebe2mi`).
- 운영 확인: 아래에 기록.
