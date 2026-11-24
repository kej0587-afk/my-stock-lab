# 실적 '이익·EPS' 칸: NVDA EPS 인식, 문장에 있는 이익 항목 표시

작성 2026-11-24 KST · 시작 `b126db95` · 근거: 보고서(61) 877·890행, 상태표 #7

## 확인한 원인

- NVDA FY2027Q3 공식 원문(SEC EX-99.1)을 직접 열어 확인한 문장:
  "GAAP and non-GAAP earnings per diluted share were $2.70 and $2.68, respectively."
  이익 패턴이 `earnings per share`만 찾아 `earnings per diluted share`를 놓쳤다 → '미연결'.
- PANW FY2027Q1은 처음 맞는 문장이 GAAP 영업이익 문장이라 '이익·EPS' 칸에 그대로 실렸다.
  값은 원문 그대로지만, 칸 이름만 보면 EPS로 오해할 수 있었다.

## 변경

- `earnings_result_sources._METRICS["profit"]`: `earnings per diluted share`, `diluted earnings per share`를 인식.
  금액 필수, 전망 문장 제외, 분기·기간 대조, 정의 문장 제외 규칙은 그대로다.
- `profit_kind(sentence)`: 인용 문장에 실제로 있는 항목(영업이익/순이익/EPS)과 기준(GAAP/조정/둘 다/미표기)을 기록.
- `report_calendar._result_detail_lines`: 이익 칸 앞에 "문장에 있는 항목: 영업이익 (GAAP) · 순이익·EPS는 이 문장에 없음"처럼 표시.
  원문 문장과 근거 링크는 그대로 둔다. 문장에서 값을 계산하거나 다른 칸을 채우지 않는다.

## 검증

- report 게이트: 수정 전 208(`b126db95` 기준 2단계 확인 때), 수정 후 208 통과(`report_r_ztt8mx`).
- 실적·SEC·DART 관련 묶음: 수정 전 710 통과·5 실패, 수정 후 같은 5건 실패(오래된 app.py 비교 테스트 등)·710 통과.
- 신규 `tests/test_earnings_profit_kind.py` 3건: NVDA 문장 인식(GAAP·조정), PANW 영업이익 문장 표시, 기준 표기.
- 운영 반영은 다음 배포 후 확인한다(NVDA는 실적 캐시가 갱신돼야 바뀐 결과가 보인다).

## 남은 것

- 영업이익·순이익·GAAP EPS·조정 EPS를 각각 별도 칸으로 모으는 것(현재는 첫 문장 하나 + 항목 표시).
