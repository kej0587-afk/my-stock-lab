# 생성 예시

보유 종목·비중은 테스트 예시이며 실제 계좌가 아닙니다. 시세·경제지표·뉴스는 실행 시 수집된 자료이며 누락은 그대로 표시합니다.

🌇 Stock Lab 자동 뉴스픽
10/18 (일) · 오후 7시
━━━━━━━━━━━━
📊  시 황
━━━━━━━━━━━━

## 기준일
생성 2026-10-18 19:06 KST
- 한국: 2026-10-16 정규장 종가 기준
- 미국: 2026-10-16 정규장 종가 기준
- 시차: 한국장은 같은 날짜 미국장보다 먼저 마감합니다. 한국 마감 후 미국 뉴스·가격은 다음 거래일 갭 리스크입니다.
  비교하는 거래일: 한국 2026-10-16 / 미국 2026-10-16. 동시 거래 결과가 아닙니다.

## 어제 대비 바뀐 것
전일 비교 없음: 이전 거래일의 저장된 점검이 없습니다.

## 한 줄 결론
미국 주요지수 동반 하락, 앞서 마감한 한국 반등과 시차가 있어 다음 개장 갭에 주의.

## 오늘의 시장 스토리
1. 코스피 +2.05%, 코스닥 +4.46%, S&P500 -1.09%, 나스닥 -2.15%, 다우 -0.34%. [근거: 시장별 정규장 일봉]
2. 2026-09 미국 CPI는 전월비 0.6%, 이전 0.4%입니다. 예상치 미연결로 서프라이즈 여부는 보류합니다. [BLS · US_CPI](https://api.bls.gov/publicAPI/v1/timeseries/data/CUSR0000SA0)
3. 관련 보도는 있으나 이 종가 움직임의 원인 미확인입니다. 마감 후 보도는 다음 세션 재료입니다. [한국경제 · 중국 CXMT 차세대 D램 위협인가 (한경 프리미엄9 TODAY)](https://news.google.com/rss/articles/CBMiWkFVX3lxTE4tTTNxUm1qRS1WU1RTNmRoRjcwWWsxZkU2eWhXUXhkV1ZNbmthczdjblFsS25uNWREdm91R2Q5eE5VQkduTkJxU2FPX3BEUzgxRXVmalcyZzNqQQ?oc=5)
4. 연결된 보유목록에서 일간 수익률 하위는 SOXL -12.74%입니다. 손익과 비중초과·레버리지 보유 사유는 별개입니다. [근거: SOXL 정규장 일봉]
5. 다음 체크는 한국 마감 뒤 미국 움직임의 국내 미국자산 ETF 반영 여부와 개장 갭입니다(시차에 따른 추정 리스크). [근거: 한국·미국 거래시간 차이]

## 경제지표
지표 | 발표치 | 예상 | 이전 | 시장 반응(금리·달러·지수)
--- | --- | --- | --- | ---
미국 CPI 2026-09 전월비 [BLS · US_CPI](https://api.bls.gov/publicAPI/v1/timeseries/data/CUSR0000SA0) | 0.6% | 미제공 | 0.4% | 이벤트 전후 동시점 반응 미수집
미국 CPI 2026-09 전년비 [BLS · US_CPI](https://api.bls.gov/publicAPI/v1/timeseries/data/CUUR0000SA0) | 3.7% | 미제공 | 3.4% | 이벤트 전후 동시점 반응 미수집
미국 근원 CPI 2026-09 전월비 [BLS · US_CORE_CPI](https://api.bls.gov/publicAPI/v1/timeseries/data/CUSR0000SA0L1E) | 0.3% | 미제공 | 0.3% | 이벤트 전후 동시점 반응 미수집
미국 근원 CPI 2026-09 전년비 [BLS · US_CORE_CPI](https://api.bls.gov/publicAPI/v1/timeseries/data/CUUR0000SA0L1E) | 2.6% | 미제공 | 2.4% | 이벤트 전후 동시점 반응 미수집
미국 PPI 2026-09 전월비 [BLS · US_PPI](https://api.bls.gov/publicAPI/v1/timeseries/data/WPSFD4) | 1.3% | 미제공 | 0.5% | 이벤트 전후 동시점 반응 미수집
미국 PPI 2026-09 전년비 [BLS · US_PPI](https://api.bls.gov/publicAPI/v1/timeseries/data/WPUFD4) | 6.3% | 미제공 | 5.6% | 이벤트 전후 동시점 반응 미수집
미국 비농업고용 증감 2026-09 전월비 [BLS · US_NONFARM_PAYROLLS](https://api.bls.gov/publicAPI/v1/timeseries/data/CES0000000001) | 29.0천 명 | 미제공 | 133.0천 명 | 이벤트 전후 동시점 반응 미수집
미국 실업률 2026-09 수준 [BLS · US_UNEMPLOYMENT](https://api.bls.gov/publicAPI/v1/timeseries/data/LNS14000000) | 4.2% | 미제공 | 4.1% | 이벤트 전후 동시점 반응 미수집
미국 소매판매  전월비 [US Census Bureau (MARTS) · US_RETAIL_SALES](https://api.census.gov/data/timeseries/eits/marts) | 미수집 | 미제공 | 미수집 | 이벤트 전후 동시점 반응 미수집
연준 목표금리 상단(결정문 아님)  수준 [Federal Reserve via FRED · US_FED_TARGET_UPPER](https://fred.stlouisfed.org/series/DFEDTARU) | 미수집 | 미제공 | 미수집 | 이벤트 전후 동시점 반응 미수집
한국 소비자물가  전년비 [ECOS/KOSIS · KR_CPI](https://ecos.bok.or.kr/api/) | 미수집 | 미제공 | 미수집 | 이벤트 전후 동시점 반응 미수집
한국 수출  전년비 [ECOS/KOSIS · KR_EXPORTS](https://ecos.bok.or.kr/api/) | 미수집 | 미제공 | 미수집 | 이벤트 전후 동시점 반응 미수집

지표는 최신 수정치 기준입니다. 전월비·전년비/계절조정 기준이 다른 수치는 서로 비교하지 않습니다. 발표일 미제공은 관측월로 대체하지 않습니다.

## 업종별 왜
- 에너지(XLE) +2.52%: 원인 미확인
- 유틸리티(XLU) +1.34%: 원인 미확인
- 기술(XLK) -3.02%: 원인 미확인
- 커뮤니케이션(XLC) -1.89%: 원인 미확인

## 내 보유 종목 영향
종목 | 일간 등락 | 보유 점검 사유 | 레버리지 환산(추정)
--- | --- | --- | ---
S&P500 코어(예시)(379800.KS) | -0.13% (2026-10-16) | 조건대기 | 해당없음
반도체 3배(예시)(SOXL) | -12.74% (2026-10-16) | 비중초과, 레버리지 보유 | SOXX -4.14% × 3 = -12.43% (추정·기초지수 대용 ETF·보수/추적오차 미반영)
비트코인 2배(예시)(BITX) | -1.96% (2026-10-16) | 조건대기, 레버리지 보유 | 추정 보류: 기초자산·ETF 동일 세션 자료 미확보

## 이번 주 일정
- 향후 7일 확정 날짜가 연결된 일정 없음. FOMC·CPI/PPI·주요 실적·BOJ 날짜를 추정하지 않습니다.

## 핵심 뉴스 5건
출처·중복 제거 기준 통과 4건. 부족한 1건은 무관한 기사로 채우지 않았습니다.
1. [반도체/AI] 중국 CXMT 차세대 D램 위협인가 [한경 프리미엄9 TODAY] · 2026-10-18T18:00:07+09:00 [한국경제 · 중국 CXMT 차세대 D램 위협인가 (한경 프리미엄9 TODAY)](https://news.google.com/rss/articles/CBMiWkFVX3lxTE4tTTNxUm1qRS1WU1RTNmRoRjcwWWsxZkU2eWhXUXhkV1ZNbmthczdjblFsS25uNWREdm91R2Q5eE5VQkduTkJxU2FPX3BEUzgxRXVmalcyZzNqQQ?oc=5)
   제목 기준: 중국 CXMT 차세대 D램 위협인가 [한경 프리미엄9 TODAY]
2. [반도체/AI] [단독] 삼성전자, ‘차세대 HBM’ TSMC와 함께 만든다 · 2026-10-18T16:47:48+09:00 [서울경제 · (단독) 삼성전자, ‘차세대 HBM’ TSMC와 함께 만든다](https://news.google.com/rss/articles/CBMiUkFVX3lxTFA3WldhTWZaaEVTWHNENi1FYXF3OERPQmN2ekIxMjhZd044R0dldVNDNkQzZ05lU3IxY253aGVXMV82U0xfT0dtM1lEV1duLU1PMmfSAVNBVV95cUxOUUpRSU10YXg2LXh0MDRsMEt0WGtveGNqVXJOSmJ2c3N5NHpXYTZvM0Z3TTAxZ2xmT01NRXdTRHlVVjhzTUxURFYtalpYWEFlcW9RUQ?oc=5)
   제목 기준: [단독] 삼성전자, ‘차세대 HBM’ TSMC와 함께 만든다
3. [매크로] 美, 인플레 재연 조짐…10월 FOMC서 금리 올리나 [한상춘의 국제경제 읽기] · 2026-10-18T17:20:47+09:00 [한국경제 · 美, 인플레 재연 조짐…10월 FOMC서 금리 올리나 (한상춘의 국제경제 읽기)](https://news.google.com/rss/articles/CBMiWkFVX3lxTE1vZnBrNFh5V0xoOG54M3pFNWdqQ2tvWklaV2NVanREdHVicUhOTjZKT3dkbEJzcHc2QzVfWUhpeWkxbjdFTHhoaHM1b3J6SXN6d0pPVkNRRXZKUQ?oc=5)
   제목 기준: 美, 인플레 재연 조짐…10월 FOMC서 금리 올리나 [한상춘의 국제경제 읽기]
4. [매크로] BOJ 총재 "금융여건 여전히 완화적…인플레 추가 가속 용인 못해" · 2026-10-17T00:54:00+09:00 [연합인포맥스 · BOJ 총재 "금융여건 여전히 완화적…인플레 추가 가속 용인 못해"](https://news.google.com/rss/articles/CBMicEFVX3lxTE9COUFKZjlsY0wtUkMxdm0xcm9pTS1WeF9JMV9fbUJfV1ZoMG1ZYjhBOE9MUHE1V3F5dFhIU3VSQzhnb2ZsckFDclRjVzVFSi0zaHUxNGNGR210d09FalpSUEY1U2w0NjFtRTN5TUVOY0w?oc=5)
   제목 기준: BOJ 총재 "금융여건 여전히 완화적…인플레 추가 가속 용인 못해"

가격·거래량 흐름은 실제 자금 유입액이 아닙니다. 가속도는 최근 3개월 수익률과 직전 3개월 수익률 차이(%p), 다이버전스는 가격과 흐름 지표 방향이 엇갈리는 상태입니다.

━━━━━━━━━━━━
기존 점검 · 수치 근거
━━━━━━━━━━━━

🎯 실행 점검
• 오늘의 전략: 레버리지 신규매수 금지 / 신규매수보다 가격 안정 확인 / 금리·변동성 관망

🧭 지수/스타일 로테이션
• 미국 세션 1D 가격 상승: 유틸리티(XLU)(+1.3%), 필수소비재(XLP)(+1.1%), 금융(XLF)(+0.5%)
• 미국 세션 1D 가격 하락: 기술(XLK)(-3.0%), 산업재(XLI)(-0.1%)
• 미국 스타일 1D 평균 분모: 성장 [XLK], 다우·방어 [XLF, XLI, XLP, XLU]
• 1D 기준 성장주보다 다우·산업재·금융·방어가 강합니다 — 성장주 -3.0%, 다우·방어 +0.7%
※ 시장별 세션의 가격수익률 비교입니다. 실제 자금 유입/유출·외국인 순매매는 미확인입니다.

📉 매크로·이벤트
• 매크로 스트레스 74/100(경고) · 기본 18 10Y 금리 +24 VIX +22 MOVE +18 유가 +0 환율 -8 = 74 (0~100 범위 적용) · 보고서용 지표(매매 게이트와 별개)
• 10Y 금리 5.10, 1개월 +3.1%, 방향 상승, 수준 경고 · 상승 부담 · 스트레스 기여 +24 [Yahoo Finance daily · 2026-10-16]
• VIX 19.99, 1개월 +29.5%, 방향 상승, 수준 경고 없음 · 급등 주의 · 스트레스 기여 +22 [Yahoo Finance daily · 2026-10-16]
• MOVE 101.10, 1개월 +25.2%, 방향 상승, 수준 경고 없음 · 급등 주의 · 스트레스 기여 +18 [Yahoo Finance daily · 2026-10-16]
• WTI 선물(CL=F) 99.02, 1개월 -2.8%, 방향 하락, 고수준 부담 · 스트레스 기여 +0 [Yahoo Finance daily · 2026-10-16]
• 환율 1340.95, 1개월 -2.6%, 방향 하락, 수준 경고 없음 · 스트레스 기여 -8 [Yahoo Finance daily · 2026-10-16]

🧭 오늘점검
• 주의/차단 후보: S&P500(379800.KS) [보유], 비트코인 2배(예시)(BITX) [보유]
• 하드차단 우선 확인: 반도체 3배(예시)(SOXL) [보유] - 비중 초과
• 하드차단 해제 기준: 비중초과=목표비중 이하, 추세방어=일봉·주봉 회복, 매크로위험=스트레스 경고 이하
• 실제 보유: S&P500(379800.KS), 반도체 3배(예시)(SOXL), 비트코인 2배(예시)(BITX)

※ 데이터 누락이 있는 자동 생성 초안: 미국 소매판매: 공식 API 키 미설정/응답 없음 / 연준 목표금리 상단(결정문 아님): 공식 API 키 미설정/응답 없음 / 한국 소비자물가: 공식 API 키 미설정/응답 없음 / 한국 수출: 공식 API 키 미설정/응답 없음 / 향후 7일 확정 일정