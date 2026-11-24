# 세계 시장 구역: 현지 지수 연결(백로그 #12)

작성 2026-11-24 KST.

## 변경

- `report_dashboard.LOCAL_INDICES`: 닛케이225(^N225, JPY), 니프티50(^NSEI, INR), 보베스파(^BVSP, BRL)를 기존 Yahoo 일봉 묶음으로 받는다.
  보고서 전용이며 순환·점수·매매 입력에는 넣지 않는다(`report_context`의 `daily_only`에 포함).
- 완료 판정은 각 거래소 현지 시각 기준이다. 이전 날짜 일봉, 또는 오늘 일봉이면 현지 마감 + 30분이 지난 경우만 쓴다
  (도쿄 15:30, 뭄바이 15:30, 상파울루 18:00 기준). 미국 달력을 빌려 쓰지 않는다.
- '세계 시장과 국가 ETF' 구역에 국가 ETF 표 아래 현지 지수 표를 둔다. 현지 통화·현지 기준일 그대로이며 ETF와 서로 환산하거나 대신 쓰지 않는다.
- 베트남 VN-Index는 미연결로 둔다. 2026-11-24 브라우저에서 확인한 Yahoo `^VNINDEX.VN` 일봉이 1개뿐이고 시각이 비정상이라 쓰지 않았다.
- 데이터가 없으면 `미연결`로 남기며 값을 채우지 않는다.

## 확인한 원자료(2026-11-24, Yahoo chart API, 브라우저)

- ^N225: Asia/Tokyo, JPY, 11-20 56,436.65 → 11-24 58,716.83
- ^NSEI: Asia/Kolkata, INR, 11-20 25,800.60 → 11-23 25,349.65
- ^BVSP: America/Sao_Paulo, BRL, 11-19 166,376 → 11-23 164,796

## 검증

- 신규 `tests/test_report_local_indices.py` 2건(현지 마감 + 30분 전후, 결측·베트남 미연결, 현지 통화 표기).
- 보고서 관련 묶음 2088 통과, 기존 실패 3건(bok 달력, company_market_reading app 비교, summary_ownership RAM 위치)은 main에서도 실패.
- report 게이트 208 통과(`report_xxmr28e6`).
