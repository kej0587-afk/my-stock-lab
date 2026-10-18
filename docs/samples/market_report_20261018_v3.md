# 생성 예시

보유 종목·비중은 테스트 예시이며 실제 계좌가 아닙니다. 시세·경제지표·뉴스는 실행 시 수집된 자료이며 누락은 그대로 표시합니다.

# Stock Lab 자동 뉴스픽

신규매수 허용 0개 / 보유 6, 관심 0 / 사유: 매크로 스트레스 74 경고 · 게이트 미제공 1개(허용으로 추정하지 않음)

## 기준일
생성 2026-10-18 23:54 KST
- 한국: 2026-10-16 정규장 종가 기준
- 미국: 2026-10-16 정규장 종가 기준
- 시차: 한국장은 같은 날짜 미국장보다 먼저 마감합니다. 한국 마감 후 미국 뉴스·가격은 다음 거래일 갭 리스크입니다.
  비교하는 거래일: 한국 2026-10-16 / 미국 2026-10-16. 동시 거래 결과가 아닙니다.

## 어제 대비 바뀐 것
전일 비교 없음: 이전 거래일의 저장된 점검이 없습니다.
샘플 계좌: 개인 전일 비교 이력 저장 안 함 · 서버 재배포로 로컬 파일이 소실되면 비교 이력도 사라집니다.

## 한 줄 결론
미국 주요지수 동반 하락, 앞서 마감한 한국 반등과 시차가 있어 다음 개장 갭에 주의.

## 오늘의 시장 스토리
- 사실: 보유 반도체 노출부터 확인: SOXX -4.14%, DRAM -5.84%, XLK -3.02%, SOXL -12.74%, RAM -11.88%. 해석(추정): 동일 업종 중첩과 레버리지가 계좌 변동을 확대할 수 있습니다. 미확인: 개별 하락 원인의 기여도. [근거: 기준 거래일 일봉·보유목록]
- 사실: 코스피 +2.05%, 코스닥 +4.46%, S&P500 -1.09%, 나스닥 -2.15%, 다우 -0.34%. [근거: 시장별 정규장 일봉]
- 사실: 2026-09 미국 PPI 전월비 1.3%, 이전 0.5% → 변화 +0.80%p · 직전 3개월 평균 0.20% 대비 +1.10%p · 이전/추세 비교이며 컨센서스 서프라이즈 아님. [BLS · US_PPI](https://api.bls.gov/publicAPI/v1/timeseries/data/WPSFD4)
- 사실: 2026-09 미국 비농업고용 증감 전월비 29.0천 명, 이전 133.0천 명 → 변화 -104.00천 명 · 직전 3개월 평균 51.33천 명 대비 -22.33천 명 · 이전/추세 비교이며 컨센서스 서프라이즈 아님. [BLS · US_NONFARM_PAYROLLS](https://api.bls.gov/publicAPI/v1/timeseries/data/CES0000000001)
- 사실: 2026-09 미국 CPI 전월비 0.6%, 이전 0.4% → 변화 +0.20%p · 직전 3개월 평균 0.03% 대비 +0.57%p · 이전/추세 비교이며 컨센서스 서프라이즈 아님. [BLS · US_CPI](https://api.bls.gov/publicAPI/v1/timeseries/data/CUSR0000SA0)
지표 선정: 단위가 다른 지표를 비교하기 위해 이전치 대비 변화 비율 순, 지표별 1개(전월비 우선). 컨센서스 순위가 아닙니다.
- 미확인: 관련 보도는 있으나 이 종가 움직임의 직접 원인·기여도는 확정하지 않습니다. [아시아경제 · 순매수 전환한 외국인…코스피 2% 상승 마감](https://news.google.com/rss/articles/CBMiYkFVX3lxTE5kN0VjV1U2cHBnVzE1eGx3djl1RjRzMmFaSGpWQ213UVZlMm5pbmpsMEJyaW16Y3pGT3hfQUt1eV8wRkxqRUhrZFVqWFg0cGNfbkhjMGZxU0YzdjVtaVRvUWdR?oc=5)
- 사실: 연결된 보유목록에서 일간 수익률 하위는 SOXL -12.74%입니다. 손익과 비중초과·레버리지 보유 사유는 별개입니다. [근거: SOXL 정규장 일봉]
- 다음 체크: 한국 마감 뒤 미국 움직임의 국내 미국자산 ETF 반영 여부와 개장 갭입니다(시차에 따른 추정 리스크). [근거: 한국·미국 거래시간 차이]

## 경제지표
지표 | 발표치 | 예상/대체 비교 | 이전 | 시장 반응(금리·달러·지수)
--- | --- | --- | --- | ---
미국 CPI 2026-09 전월비 · 발표 2026-10-14T08:30:00-04:00 [BLS · US_CPI](https://api.bls.gov/publicAPI/v1/timeseries/data/CUSR0000SA0) | 0.6% | 컨센서스 미연결 · 이전 대비 +0.20%p · 직전 3개월 평균 0.03% | 0.4% | 2026-10-14 · 10Y -2.70bp, 원/달러 +0.46%, 나스닥 -1.88% · 동일일 움직임이며 인과가 아님(환율은 공급처 일봉)
미국 CPI 2026-09 전년비 · 발표 2026-10-14T08:30:00-04:00 [BLS · US_CPI](https://api.bls.gov/publicAPI/v1/timeseries/data/CUUR0000SA0) | 3.7% | 컨센서스 미연결 · 이전 대비 +0.30%p · 직전 3개월 평균 3.43% | 3.4% | 2026-10-14 · 10Y -2.70bp, 원/달러 +0.46%, 나스닥 -1.88% · 동일일 움직임이며 인과가 아님(환율은 공급처 일봉)
미국 근원 CPI 2026-09 전월비 · 발표 2026-10-14T08:30:00-04:00 [BLS · US_CORE_CPI](https://api.bls.gov/publicAPI/v1/timeseries/data/CUSR0000SA0L1E) | 0.3% | 컨센서스 미연결 · 이전 대비 +0.00%p · 직전 3개월 평균 0.17% | 0.3% | 2026-10-14 · 10Y -2.70bp, 원/달러 +0.46%, 나스닥 -1.88% · 동일일 움직임이며 인과가 아님(환율은 공급처 일봉)
미국 근원 CPI 2026-09 전년비 · 발표 2026-10-14T08:30:00-04:00 [BLS · US_CORE_CPI](https://api.bls.gov/publicAPI/v1/timeseries/data/CUUR0000SA0L1E) | 2.6% | 컨센서스 미연결 · 이전 대비 +0.20%p · 직전 3개월 평균 2.50% | 2.4% | 2026-10-14 · 10Y -2.70bp, 원/달러 +0.46%, 나스닥 -1.88% · 동일일 움직임이며 인과가 아님(환율은 공급처 일봉)
미국 PPI 2026-09 전월비 · 발표 2026-10-15T08:30:00-04:00 [BLS · US_PPI](https://api.bls.gov/publicAPI/v1/timeseries/data/WPSFD4) | 1.3% | 컨센서스 미연결 · 이전 대비 +0.80%p · 직전 3개월 평균 0.20% | 0.5% | 2026-10-15 · 10Y -10.10bp, 원/달러 -0.07%, 나스닥 +0.08% · 동일일 움직임이며 인과가 아님(환율은 공급처 일봉)
미국 PPI 2026-09 전년비 · 발표 2026-10-15T08:30:00-04:00 [BLS · US_PPI](https://api.bls.gov/publicAPI/v1/timeseries/data/WPUFD4) | 6.3% · BLS 원문 재확인(2026-10-18) 일치 [공식 발표문](https://www.bls.gov/news.release/archives/ppi_10152026.htm) | 컨센서스 미연결 · 이전 대비 +0.70%p · 직전 3개월 평균 5.37% | 5.6% | 2026-10-15 · 10Y -10.10bp, 원/달러 -0.07%, 나스닥 +0.08% · 동일일 움직임이며 인과가 아님(환율은 공급처 일봉)
미국 비농업고용 증감 2026-09 전월비 · 발표 2026-10-02T08:30:00-04:00 [BLS · US_NONFARM_PAYROLLS](https://api.bls.gov/publicAPI/v1/timeseries/data/CES0000000001) | 29.0천 명 | 컨센서스 미연결 · 이전 대비 -104.00천 명 · 직전 3개월 평균 51.33천 명 | 133.0천 명 | 2026-10-02 · 10Y +4.00bp, 원/달러 +0.28%, 나스닥 +1.19% · 동일일 움직임이며 인과가 아님(환율은 공급처 일봉)
미국 실업률 2026-09 수준 · 발표 2026-10-02T08:30:00-04:00 [BLS · US_UNEMPLOYMENT](https://api.bls.gov/publicAPI/v1/timeseries/data/LNS14000000) | 4.2% | 컨센서스 미연결 · 이전 대비 +0.10%p · 직전 3개월 평균 4.13% | 4.1% | 2026-10-02 · 10Y +4.00bp, 원/달러 +0.28%, 나스닥 +1.19% · 동일일 움직임이며 인과가 아님(환율은 공급처 일봉)
미국 소매판매  전월비 [US Census Bureau (MARTS) · US_RETAIL_SALES](https://api.census.gov/data/timeseries/eits/marts) | 미수집 | 컨센서스 미연결 | 미수집 | 발표일 미연결/미발표로 동일일 비교 보류
연준 목표금리 상단(결정문 아님)  수준 [Federal Reserve via FRED · US_FED_TARGET_UPPER](https://fred.stlouisfed.org/series/DFEDTARU) | 미수집 | 컨센서스 미연결 | 미수집 | 발표일 미연결/미발표로 동일일 비교 보류
한국 소비자물가  전년비 [Bank of Korea ECOS · KR_CPI](https://ecos.bok.or.kr/api/) | 미수집 | 컨센서스 미연결 | 미수집 | 발표일 미연결/미발표로 동일일 비교 보류
한국 수출  전년비 [Bank of Korea ECOS · KR_EXPORTS](https://ecos.bok.or.kr/api/) | 미수집 | 컨센서스 미연결 | 미수집 | 발표일 미연결/미발표로 동일일 비교 보류

지표는 최신 수정치 기준입니다. 전월비·전년비/계절조정 기준이 다른 수치는 서로 비교하지 않습니다. 발표일 미제공은 관측월로 대체하지 않습니다.

## 업종별 왜
업종 | 사실 | 해석(추정) | 미확인
--- | --- | --- | ---
에너지(XLE) | 사실: XLE 일간 +2.52% · 2026-10-16 [공급처 일봉 종가] | 해석(추정): 동일일 WTI +1.07%와 업종이 같은 방향; 에너지 가격 경로를 점검하되 선물·주식 수익률만으로 업종 이익 기여를 확정하지 않습니다 | 미확인: 해당 업종 움직임의 개별 원인·기여도는 확정 자료 없음
유틸리티(XLU) | 사실: XLU 일간 +1.34% · 2026-10-16 [공급처 일봉 종가] | 해석(추정): 동일일 10Y +0.90bp와 업종 +1.34%; 단순한 금리-주가 역방향 설명과 어긋나므로 다른 요인을 확인해야 함 [연준 할인율 설명](https://www.federalreserve.gov/publications/may-2021-asset-valuations.htm) | 미확인: 해당 업종 움직임의 개별 원인·기여도는 확정 자료 없음
메모리(DRAM) | 사실: DRAM 일간 -5.84% · 2026-10-16 [공급처 일봉 종가] | 해석(추정): 수집된 업종 가격만으로 금리·실적 등 경제적 경로를 구분할 수 없습니다 | 미확인: 해당 업종 움직임의 개별 원인·기여도는 확정 자료 없음 · 관련 보도(인과 아님): [Chosunbiz · Wall Street doubts CXMT 4F² DRAM edge as Korea retains density and yield lead](https://news.google.com/rss/articles/CBMiekFVX3lxTE16WE9TTXAwUkhxdThhMFBobzJFMHN3aHNWVEJaZTkwdlUtcEF3eWhFdjZodjNTRkk4aURiZzRrbWtUMW9PNWp6OTl5dkwzbkt3M2FQd0R1WEZ6VHl6ckJQdENmR3RjOHFtbTlxVlp3U3h6RVRLa2ZTSE1n0gGOAUFVX3lxTE9YQU1yS0ZBU1FHYzdsZ1QzeXJqb0NYTlBSaE1qNTFSSF9TUGNWR1V1YzlweEEwbGI1bU5GNUxDN3pHX3gtckxyc0tzdUJLTUtvTmNaWkdGeUpEM3o0M3RYTXhqOHdQWXNSQm1OaUxrNHo4R3dqaF9ZU0dYREd0NnRMdlA2aFVWWHV6bG0tS0E?oc=5)
반도체(SOXX) | 사실: SOXX 일간 -4.14% · 2026-10-16 [공급처 일봉 종가] | 해석(추정): 수집된 업종 가격만으로 금리·실적 등 경제적 경로를 구분할 수 없습니다 | 미확인: 해당 업종 움직임의 개별 원인·기여도는 확정 자료 없음 · 관련 보도(인과 아님): [Chosunbiz · Wall Street doubts CXMT 4F² DRAM edge as Korea retains density and yield lead](https://news.google.com/rss/articles/CBMiekFVX3lxTE16WE9TTXAwUkhxdThhMFBobzJFMHN3aHNWVEJaZTkwdlUtcEF3eWhFdjZodjNTRkk4aURiZzRrbWtUMW9PNWp6OTl5dkwzbkt3M2FQd0R1WEZ6VHl6ckJQdENmR3RjOHFtbTlxVlp3U3h6RVRLa2ZTSE1n0gGOAUFVX3lxTE9YQU1yS0ZBU1FHYzdsZ1QzeXJqb0NYTlBSaE1qNTFSSF9TUGNWR1V1YzlweEEwbGI1bU5GNUxDN3pHX3gtckxyc0tzdUJLTUtvTmNaWkdGeUpEM3o0M3RYTXhqOHdQWXNSQm1OaUxrNHo4R3dqaF9ZU0dYREd0NnRMdlA2aFVWWHV6bG0tS0E?oc=5)
기술(XLK) | 사실: XLK 일간 -3.02% · 2026-10-16 [공급처 일봉 종가] | 해석(추정): 동일일 10Y +0.90bp와 업종 -3.02%; 금리 상승에 따른 할인율 부담 가능성 [연준 할인율 설명](https://www.federalreserve.gov/publications/may-2021-asset-valuations.htm) | 미확인: 해당 업종 움직임의 개별 원인·기여도는 확정 자료 없음
통신(XLC) | 사실: XLC 일간 -1.89% · 2026-10-16 [공급처 일봉 종가] | 해석(추정): 동일일 10Y +0.90bp와 업종 -1.89%; 금리 상승에 따른 할인율 부담 가능성 [연준 할인율 설명](https://www.federalreserve.gov/publications/may-2021-asset-valuations.htm) | 미확인: 해당 업종 움직임의 개별 원인·기여도는 확정 자료 없음

## 내 보유 종목 영향
종목 | 일간 등락 | 레버리지 환산 | 상태/사유
--- | --- | --- | ---
나스닥100 코어(예시)(379810.KS) | +0.00% (2026-10-16) | 월요일 갭 예상 영향(추정): QQQ -2.50% × 1 = -2.50% · 2026-10-16 · 환율·선물·추적오차 미반영, 확정 갭/가격 예측 아님 | 비중초과
나스닥100 2배(예시)(418660.KS) | +0.12% (2026-10-16) | 월요일 갭 예상 영향(추정): QQQ -2.50% × 2 = -5.00% · 2026-10-16 · 환율·선물·추적오차 미반영, 확정 갭/가격 예측 아님 | 비중초과, 레버리지 보유
메모리 2배(예시)(RAM) | -11.88% (2026-10-16) | 일간 배수 환산(추정): DRAM -5.84% × 2 = -11.68% · 2026-10-16 · 대용 기초자산, 보수·선물 베이시스·추적오차 미반영 | 비중초과, 레버리지 보유
S&P500 코어(예시)(379800.KS) | -0.13% (2026-10-16) | 월요일 갭 예상 영향(추정): ^GSPC -1.09% × 1 = -1.09% · 2026-10-16 · 환율·선물·추적오차 미반영, 확정 갭/가격 예측 아님 | 개별 위험사유 없음
반도체 3배(예시)(SOXL) | -12.74% (2026-10-16) | 일간 배수 환산(추정): SOXX -4.14% × 3 = -12.43% · 2026-10-16 · 대용 기초자산, 보수·선물 베이시스·추적오차 미반영 | 비중초과, 레버리지 보유
비트코인 2배(예시)(BITX) | -1.96% (2026-10-16) | 일간 배수 환산(추정): BTC(미국장 마감→마감) -1.01% × 2 = -2.02% · 2026-10-16 · 대용 기초자산, 보수·선물 베이시스·추적오차 미반영 | 레버리지 보유

## 관심 후보 상위 3개
- 관심 후보 미연결/없음

## 이번 주 일정
- 향후 7일 일정 없음(연결된 공식 일정: Federal Reserve FOMC)
- 일정 미연결: BLS CPI · http_403
- 일정 미연결: BLS PPI · http_403
- 일정 미연결: BLS Employment Situation · http_403

## 핵심 뉴스 5건
기준 거래일 마감시황 우선. 이전 거래일의 마감 회고는 제외하며, 마감 후 회고는 사후보도로 표시합니다.
1. [마감 시황] 순매수 전환한 외국인…코스피 2% 상승 마감 · 2026-10-16T16:53:00+09:00 · 마감 후 회고(인과 확정 아님) [아시아경제 · 원문](https://news.google.com/rss/articles/CBMiYkFVX3lxTE5kN0VjV1U2cHBnVzE1eGx3djl1RjRzMmFaSGpWQ213UVZlMm5pbmpsMEJyaW16Y3pGT3hfQUt1eV8wRkxqRUhrZFVqWFg0cGNfbkhjMGZxU0YzdjVtaVRvUWdR?oc=5)
   제목 기준: 순매수 전환한 외국인…코스피 2% 상승 마감
2. [마감 시황] [마켓뷰] 코스피, 8거래일 만에 2% 상승 마감… 코스닥도 4%대 반등 - 조선비즈 · 2026-10-16T16:10:00+09:00 [Chosunbiz · 원문](https://news.google.com/rss/articles/CBMinAFBVV95cUxPSzdJdlNYSC1YRVJXRUt1N2wxYndJeUxISnhyZElVSXE4MmkwVHZGeHh4TGJ6ZGF2VDN6YThtMVIyRHkwM3BRYXc5N1Z1N2RLLTM5Rlh4bEQwQnBsZnhrY1JCSFZJclhuRDFvVnBxN1dQTjRMWEVyNlVYTVJBVmhtQ0NzdFhMYVdqdzlnUHRxQU94ZUVFcW5IaXF2MHjSAZwBQVVfeXFMT0s3SXZTWEgtWEVSV0VLdTdsMWJ3SXlMSEp4cmRJVUlxODJpMFR2Rnh4eExiemRhdlQzemE4bTFSMkR5MDNwUWF3OTdWdTdkSy0zOUZYeGxEMEJwbGZ4a2NSQkhWSXJYbkQxb1ZwcTdXUE40TFhFcjZVWE1SQVZobUNDc3RYTGFXanc5Z1B0cUFPeGVFRXFuSGlxdjB4?oc=5)
   제목 기준: [마켓뷰] 코스피, 8거래일 만에 2% 상승 마감… 코스닥도 4%대 반등 - 조선비즈
3. [반도체/AI] Wall Street doubts CXMT 4F² DRAM edge as Korea retains density and yield lead · 2026-10-16T15:16:00+09:00 [Chosunbiz · 원문](https://news.google.com/rss/articles/CBMiekFVX3lxTE16WE9TTXAwUkhxdThhMFBobzJFMHN3aHNWVEJaZTkwdlUtcEF3eWhFdjZodjNTRkk4aURiZzRrbWtUMW9PNWp6OTl5dkwzbkt3M2FQd0R1WEZ6VHl6ckJQdENmR3RjOHFtbTlxVlp3U3h6RVRLa2ZTSE1n0gGOAUFVX3lxTE9YQU1yS0ZBU1FHYzdsZ1QzeXJqb0NYTlBSaE1qNTFSSF9TUGNWR1V1YzlweEEwbGI1bU5GNUxDN3pHX3gtckxyc0tzdUJLTUtvTmNaWkdGeUpEM3o0M3RYTXhqOHdQWXNSQm1OaUxrNHo4R3dqaF9ZU0dYREd0NnRMdlA2aFVWWHV6bG0tS0E?oc=5)
   제목 단서 해석: 중국 메모리 업체 CXMT 관련 소식. 세부 내용·가격 영향은 미확인
4. [마감 시황] '전날 7%대 급락' 코스피, 1% 내외 강세…코스닥 2%대↑(종합) · 2026-10-16T09:36:15+09:00 [연합뉴스 · 원문](https://news.google.com/rss/articles/CBMiYEFVX3lxTFBlaUYxMlFvWnZmV1JHT2FoUmpIM29DY21DbUlVbTN5MUprMzh4Y0E2UE9fWXpOWmRNSWhVeHJCeC1CY1JpbTNmd21NaXo1SWRtLVdBeFRCSDk2UUhHd1NqedIBYEFVX3lxTFBlaUYxMlFvWnZmV1JHT2FoUmpIM29DY21DbUlVbTN5MUprMzh4Y0E2UE9fWXpOWmRNSWhVeHJCeC1CY1JpbTNmd21NaXo1SWRtLVdBeFRCSDk2UUhHd1NqeQ?oc=5)
   제목 기준: '전날 7%대 급락' 코스피, 1% 내외 강세…코스닥 2%대↑(종합)
5. [마감 시황] [마켓뷰] 휘청했던 코스피, 변동성 이어지나 반등 시도하나 · 2026-10-16T08:13:21+09:00 [연합뉴스 · 원문](https://news.google.com/rss/articles/CBMiYEFVX3lxTFBrUmo0T1pKWTl6TDh4aV9WNHk4cGZtQXVheGx3RC1zOWM1TDZaWFVRbllRc29fZHA4ZmtaSE94NlkzYnBjMFFJMUd3bm5YakJsMWtTQnVqSW1JXzlzZnR0TtIBYEFVX3lxTFBrUmo0T1pKWTl6TDh4aV9WNHk4cGZtQXVheGx3RC1zOWM1TDZaWFVRbllRc29fZHA4ZmtaSE94NlkzYnBjMFFJMUd3bm5YakJsMWtTQnVqSW1JXzlzZnR0Tg?oc=5)
   제목 기준: [마켓뷰] 휘청했던 코스피, 변동성 이어지나 반등 시도하나

가격·거래량 흐름은 실제 자금 유입액이 아닙니다. 가속도는 최근 3개월 수익률과 직전 3개월 수익률 차이(%p), 다이버전스는 가격과 흐름 지표 방향이 엇갈리는 상태입니다.

## 다음 세션 재료
- 제목 기준: ‘빚투’ 부메랑…코스피 폭락에 1주일 새 3천억 강제청산 · 2026-10-18T18:43:00+09:00 [한겨레 · 원문](https://news.google.com/rss/articles/CBMiZEFVX3lxTE4wUGpNSER0TGxPR2NiNWNmbndSNURyMW5fT25JUjV2QkhLRGczd2VpNDR4WVRGUnN6SUJlR0NNbDViZFZSQTdRYTBmVkFXN3pCSjdhUFBsUjV3Ylhucm1faG9ZbFg?oc=5)
- 제목 기준: 지난주 14.5% 급락한 코스피…반등 열쇠는 외국인 · 2026-10-18T09:24:00+09:00 [연합뉴스TV · 원문](https://news.google.com/rss/articles/CBMiZ0FVX3lxTE9TUWRpLWZXRFZXN3NyaGdXZTAyTHRUaER5ZkVieE90Wm5qckdDcWZmdEpyRmJPcTdfenJpY29sdl94T3ZIZFBqUG1wS0JabVVsSDVuajJvTXdkMWlxanU2Wk9HdXltN1U?oc=5)
- 제목 기준: [주간증시전망]급락 딛고 반등한 코스피, 금주 방향성은…外人 수급·실적이 관건 · 2026-10-18T07:00:00+09:00 [뉴시스 · 원문](https://news.google.com/rss/articles/CBMieEFVX3lxTFBGc2phZHJtNm9tbU82Rjd1YzZlTmZtX1BacVkyZlJ3amM4NXVldC16RWtpVFRqRFE2aXdpOWxnOTQ2S0o1V0IzMnlkTzFpcm1JMU1JMXFGY2F3YWZtM3J4RnlONU02WUo3MDQ5dEpGaHduMk5jU1FIbdIBeEFVX3lxTFBGc2phZHJtNm9tbU82Rjd1YzZlTmZtX1BacVkyZlJ3amM4NXVldC16RWtpVFRqRFE2aXdpOWxnOTQ2S0o1V0IzMnlkTzFpcm1JMU1JMXFGY2F3YWZtM3J4RnlONU02WUo3MDQ5dEpGaHduMk5jU1FIbQ?oc=5)
- 제목 기준: 7일 내리막 끝 반등한 코스피…‘AI 불안’ 언제 떨쳐낼까 [선데이머니카페] · 2026-10-18T07:00:00+09:00 [서울경제 · 원문](https://news.google.com/rss/articles/CBMiU0FVX3lxTE5TbGdjSlRldk40TzNfVTFsckhHSDQtNE5OclZ2cEZfQ2FKNzdsVUluZG1XcGt1RGJGTlJ6VUtoRVNxaGo4b2NkQTNXcVozMzVMbWF30gFTQVVfeXFMTlNsZ2NKVGV2TjRPM19VMWxySEdINC00Tk5yVnZwRl9DYUo3N2xVSW5kbVdwa3VEYkZOUnpVS2hFU3FoajhvY2RBM1dxWjMzNUxtYXc?oc=5)

## 매크로 수치 근거
기본 18 10Y 금리 +24 VIX +22 MOVE +18 유가 +0 환율 -8 = 74 (0~100 범위 적용)

지표 | 수준 | 1개월 변화 | 비교 기준일 → 종가 기준일 | 상태 | 스트레스 기여
--- | --- | --- | --- | --- | ---
10Y 금리 | 5.10 | +3.05% | 2026-09-17 → 2026-10-16 | 수준 경고 · 상승 부담 | +24
VIX | 19.99 | +29.47% | 2026-09-17 → 2026-10-16 | 수준 경고 없음 · 급등 주의 | +22
MOVE | 101.10 | +25.23% | 2026-09-16 → 2026-10-16 | 수준 경고 없음 · 급등 주의 | +18
WTI 선물(CL=F) | 99.02 | -2.84% | 2026-09-17 → 2026-10-16 | 고수준 부담 | +0
환율 | 1,340.95 | -2.59% | 2026-09-17 → 2026-10-16 | 수준 경고 없음 | -8

유가 90~100달러 하락 구간의 +0: 고수준 부담은 유지하며 하락 완화점수(-8)를 주지 않습니다. 기존 +18 수준 경고는 100달러부터입니다. 산식·매매 임계값은 바꾸지 않았습니다.

데이터 누락:
- 이전 거래일 마감 회고: 37건 제외
- 명시된 시장 또는 해당 시장의 유효한 세션 없음: 23건 제외
- 뉴스 시간창 밖 또는 미래 발행시각: 322건 제외
- US: next_session_news 출처·날짜·중복 검증 후 채택 뉴스 없음
- 미국 소매판매: 공식 API 키 미설정/응답 없음
- 연준 목표금리 상단(결정문 아님): 공식 API 키 미설정/응답 없음
- 한국 소비자물가: 공식 API 키 미설정/응답 없음
- 한국 수출: 공식 API 키 미설정/응답 없음