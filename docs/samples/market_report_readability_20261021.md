# 시황 가독성 검증 예시

가격·매크로·보유비중·판정 이력은 회귀 테스트 입력이며 실제 계좌/최신 시세가 아닙니다. 뉴스만 공개 RSS를 조회했습니다. 날짜·출처 검증에서 탈락한 기사는 근거로 쓰지 않습니다.

# Stock Lab 자동 뉴스픽 · 2026-10-21 00:36 KST

신규매수 허용 0개 / 보유 1, 관심 2 / 보고서 매크로 스트레스 60 경고(실행 여부는 종목별 게이트)

## 기준일
생성 2026-10-21 00:36 KST
- 보고서 모드: 마감 후·다음 개장 전 · 한국 정규장 시간대 기준, 특별 휴장·거래시간 변경은 별도 확인

시장·확정 종가 기준 | 생성 시점 상태 | 진행 중 세션 | 달력 확인
--- | --- | --- | ---
한국: 2026-10-20 정규장 종가 기준 | 마감 후·다음 개장 전 | 없음 | 정규장 시간 기준; 특별 휴장·단축장 별도 확인
미국: 2026-10-19 정규장 종가 기준 | 장중 | 2026-10-20 | 정규장 시간 기준; 특별 휴장·단축장 별도 확인

- 시차: 한국장은 같은 날짜 미국장보다 먼저 마감합니다. 한국 마감 후 미국 뉴스·가격은 다음 거래일 갭 리스크입니다.
  비교하는 거래일: 한국 2026-10-20 / 미국 2026-10-19. 동시 거래 결과가 아닙니다.
진행 중 세션의 장중 수치는 확정 종가 표와 별도이며 해당 세션 종가가 아닙니다.

## 한 줄 결론
AI 신용우려(IT조선) · 외국인·기관 동반 매도(서울경제) 관련 보도가 나온 가운데(기사 주장), 코스피는 약세를 이어갔습니다(-3.73%, 2026-10-20 확정 종가) [IT조선 · 배경 보도](https://news.google.com/rss/articles/CBMidEFVX3lxTE5VRjJ0elJhVmdLNmFpZnZ0MUg5MGp3X2ZLWW45TFd1ZWhUT01iUElQS09DcF9LSzBHUlV6S3dGMm1WVlE2SjQweVl1TTMyQmFBNFZHdlBhczZWWWNSVm42WllQM2NNVG8yWlpJMGUwUzV2VDJX0gF0QVVfeXFMTlVGMnR6UmFWZ0s2YWlmdnQxSDkwandfZktZbjlMV3VlaFRPTWJQSVBLT0NwX0tLMEdSVXpLd0YybVZWUTZKNDB5WXVNMzJCYUE0Vkd2UGFzNlZZY1JWbjZaWVAzY01UbzJaWkkwZTBTNXZUMlc?oc=5) [서울경제 · 배경 보도](https://news.google.com/rss/articles/CBMiUkFVX3lxTE51SWdqY0VSeEpWNnJVbU5qdFR2ZDFBd21MN1BaUE90U0JxZndQdV9qWjNJNnN4TGxjWW1RT0UtSFhGajljSXlBOXFPcWkzOWRLcWfSAVNBVV95cUxNVllGbzBBSVNtSmp1NVU4MkNNUE54czFjM0hNTFFOV3NSaVRZRGppeHRHb0szN01YdS04NmJXbEZKZ1N4RzNmOVV4SVBERVpqR3FVMA?oc=5). 미국 반도체는 반등을 시도 중입니다(+0.42%, 2026-10-20 장중·확정 아님). 다만 금리·유가 부담과 반도체 중기 약세 환경에서는 반등 지속성을 확인할 국면입니다(종합 해석).

## 내 보유 종목 영향
계좌 추정 보류: 종가 연결 비중 1.0%로 90% 미만. 장전 대체 합산은 연결 비중 1.0%로 헤드라인 제외. 한국 최신 종가가 미국 기준일보다 뒤여서 이미 반영된 국내 미국지수 ETF를 장전 값으로 다시 치환하지 않음. 계좌 일간 기여 합계(추정): +0.02%p · 연결 비중 1.0% · 379810/379800/418660 집중도 0.0%. 현재비중 가중, 현금·미연결분 제외, 환율·거래 미반영. 갭 미연결 종목은 대체 합산에서 제외. 일간 합계와 갭 기여를 단순 합산하지 않음.
미국 2026-10-20 장중 별도 추정(확정 아님): 미국 보유분 기여 +0.00%p(비중 1.0%), 다음 한국장 미국지수 ETF 갭 시나리오 기여 +0.00%p(비중 0.0%). 시세 시각 미제공 · 종가 계좌 추정과 합산 금지, 환율·선물·추적오차 미반영.
재현 기준(내부 추정): 행별 현재비중(%) × 일간 수익률(%) ÷ 100 = 계좌 기여(%p). 아래 수치는 반올림 표시이며 실제 체결 손익과 별도입니다.

종목 | 기준일 일간(실제) | 개장 전 갭 시나리오/배수 참고(추정) | 당일 현재(실제) | 상태/사유
--- | --- | --- | --- | ---
반도체 ETF(SOXX) | +1.73% (2026-10-19 확정 종가) | 해당없음 | +0.42% (2026-10-20 장중 진행·확정 아님; 시각 미제공) | 개별 위험사유 없음, 현재비중 1.0000%, 일간 기여 +0.0173%p(내부 추정)

## 오늘의 시장 스토리

종합 판단 근거 | 확인 내용
--- | ---
시장 | 코스피 최신 확정 종가 -3.73%(2026-10-20 확정 종가) · 약세 지속 / 미국 반도체 +0.42%(2026-10-20 장중·확정 아님) · 반등 시도
배경 보도 | AI 신용우려(IT조선) · 외국인·기관 동반 매도(서울경제)(기사 주장·기여도 미확정)
매크로 | 스트레스 60 경고 · 10Y 금리 5.14(수준 경고 · 상승 부담) / 유가 103.66(수준 경고 · 상승 부담) · 미국 2026-10-19 종가 기준
중기 가격·거래량 | SOXX 3M -7.70%(2026-10-19 종가) / XLE 3M +10.00%(2026-10-19 종가) · 가격·거래량 기반, 실제 자금 유출입액 아님


관측 축 | 확인된 수치·범위
--- | ---
미국 업종 종가 | 미국 반도체 +1.73%(2026-10-19 확정 종가)
한국 지수 종가 | 직전 코스피 -3.73%, 5D -8.00% (2026-10-20 확정 종가)
최근 발표 지표 | 최근 3거래일 이내 발표일이 확인된 주요 발표치 없음/미연결

보도상 배경 후보 | 대상 거래일 | 출처·보도 시각
--- | --- | ---
[마감] 코스피, AI 신용우려에 3% 빠져 다시 5500선 | KR 2026-10-20 | [마감 후 보도] [IT조선 · 원문](https://news.google.com/rss/articles/CBMidEFVX3lxTE5VRjJ0elJhVmdLNmFpZnZ0MUg5MGp3X2ZLWW45TFd1ZWhUT01iUElQS09DcF9LSzBHUlV6S3dGMm1WVlE2SjQweVl1TTMyQmFBNFZHdlBhczZWWWNSVm42WllQM2NNVG8yWlpJMGUwUzV2VDJX0gF0QVVfeXFMTlVGMnR6UmFWZ0s2YWlmdnQxSDkwandfZktZbjlMV3VlaFRPTWJQSVBLT0NwX0tLMEdSVXpLd0YybVZWUTZKNDB5WXVNMzJCYUE0Vkd2UGFzNlZZY1JWbjZaWVAzY01UbzJaWkkwZTBTNXZUMlc?oc=5) 10/20 16:15 KST
U.S. Stocks Mostly Higher as AI Credit Worries Abate | US 2026-10-19 | [한국 장전 보도 / US 미국장 마감 회고 · 기사 주장] [WSJ · 원문](https://news.google.com/rss/articles/CBMinwFBVV95cUxNQlUyMFVFazFiUzkwOVR1LXd1TlBlWWNnd3VPLVJuVHd3Q2pjd0dIbnl5cnBzZ0p6SXpYSGMya21Jb004amZSUHpIQVRIYjhkMTBRdlFMeVNwZmYyZTlJdFdSbU5mLWhWdUF3MGxIWUstRkV4X0dvdmlxd3hIV2M1OEJPQUdmeXhDbzdYc094dHFLU3JsZEZZQjZpczNDcEU?oc=5) 10/20 05:58 KST
AI stocks lead a rebound on Wall Street as European markets drop following protests | US 2026-10-19 | [한국 장전 보도 / US 미국장 마감 회고 · 기사 주장] [AP News · 원문](https://news.google.com/rss/articles/CBMijAFBVV95cUxPVXpsQTBIVTFZNVR4LVdWd2pmbHBUa18tWGRnZmFqVXFvN1dCaW9vTmRxcXNOVVZFNENxTjl2d3lTTXV3TU9aRkxhUzJSNWI5SlFyY1ZoazVBakQwN2VWVzdvYnQ3RU0zQWFjYzA5ZFJ2bFFQeHhYQTRHUTBxcFlHUXQzMV8xMEpTMmR6bA?oc=5) 10/20 05:51 KST

보도 해석의 후보이며 인과·기여도는 미확정입니다. 마감 후 회고는 당일 사건을 설명하는 사후 주장으로 구분합니다. 신용 충격의 파급 범위는 같은 세션 신용 스프레드·개별 채권·수급 자료 없이는 확정하지 않습니다.
지표 서사 기준: 생성시각의 해당 시장 현지 날짜를 포함한 최근 3거래일 이내 발표일만 사용(미국 개장 전에도 현지 당일 포함). 오래된·미래·발표일 미상·비거래일 지표는 경제지표 표에 유지합니다.
- 한국 발표일 범위: 2026-10-19~2026-10-20 (거래일 이력 부족, 확인된 거래일만 적용)
- 미국 발표일 범위: 2026-10-16~2026-10-20 (미국 정규장 달력, 특별 휴장 별도 확인)
- 수급 주체 보도 2건(제목 기준·기사 주장, 순매수액 미검증): [마감 후 보도] [서울경제 · 外人·기관 동반 매도 공세…코스피, 3.73% 급락 마감 (마켓시그널)](https://news.google.com/rss/articles/CBMiUkFVX3lxTE51SWdqY0VSeEpWNnJVbU5qdFR2ZDFBd21MN1BaUE90U0JxZndQdV9qWjNJNnN4TGxjWW1RT0UtSFhGajljSXlBOXFPcWkzOWRLcWfSAVNBVV95cUxNVllGbzBBSVNtSmp1NVU4MkNNUE54czFjM0hNTFFOV3NSaVRZRGppeHRHb0szN01YdS04NmJXbEZKZ1N4RzNmOVV4SVBERVpqR3FVMA?oc=5) 10/20 16:10 KST / [마감 후 보도] [아시아경제 · 코스피, 외국인·기관 매도 확대에 3% 하락 마감](https://news.google.com/rss/articles/CBMiYEFVX3lxTE9GY0F0d1F2QVVXamFFYmxSYmplS2UzQjJERUMwRlNhQUhBSlh6U21COWk1STJ2dUFmSko2ZHBNd3ZFSDZGMzR2MlNWeVdWOEhQMHZSVkZxMFhsR2p2YlR3Qg?oc=5) 10/20 15:51 KST
- 사실: 미국 2026-10-20 장중 진행·확정 아님: SOXX +0.42% (시각 미제공). [근거: 정규장 5분봉·직전 확정 종가]
- 사실: 보유 반도체 노출부터 확인: SOXX +1.73%(2026-10-19 확정 종가). 해석(추정): 동일 업종 중첩과 레버리지가 계좌 변동을 확대할 수 있습니다. 미확인: 개별 하락 원인의 기여도. [근거: 기준 거래일 일봉·보유목록]
- 한국 다일 맥락(2026-10-20): 코스피 5D -8.00%
- 제목 기준 보도(기사 주장): [마감 후 보도] [연합뉴스 · 코스피, 3.7% 급락한 5,552 마감…최근 이틀 반등분 모두 반납(종합)](https://news.google.com/rss/articles/CBMiW0FVX3lxTFBnemRkS2ZKT21EOHlPNzU5aTh5VW9vaTIwMWI5Z2pDT19ydjlfUzZVeEI2dzl3Vm5kcTZTT1V4cUFMYmpZWDEwM2h5U3d6elRIOFRGQWdmNzY0ZlnSAWBBVV95cUxNM1BONlgyUDBDQ0wzTHZ5WjQ2LV9qYXpwMkNSajFpUTFqeDVUN3BpaDRYTTZqTEFIVVBBZDFMYjlKMkdxVW56Y2w3ZW1xVWg1Ujd6SnF1WWpNZS1IVG5TcDc?oc=5) 10/20 16:23 KST
- 다음 체크: 한국 개장 후 실제 등락과 장전 시나리오의 차이를 확인합니다. · 현재 선물 관측(미국 기준일 16:00 ET 대비, 지연 가능): NQ=F 미수집(수집 실패/지연 또는 비교 시각 자료 미수집) / ES=F 미수집(수집 실패/지연 또는 비교 시각 자료 미수집)

## 경제지표
지표 | 발표치 | 예상/대체 비교 | 이전 | 시장 반응(금리·달러·지수)
--- | --- | --- | --- | ---
CPI/PPI·고용·소매판매·FOMC·한국 수출/물가 | 미수집 | 미제공 | 미수집 | 이벤트 전후 동시점 자료 없음

## 업종별 왜
미확인: 공통 한계로 기사 내용은 보도 주장입니다. 업종 등락의 개별 원인·기여도는 확정하지 않습니다.
보고용 구분 기준: 시장 대비 초과수익 = 업종 일간 − 동일 시장·동일 종가일 지수 일간(KR ^KS11 / US ^GSPC). 절대 초과폭 1.00%p 미만은 시장 공통 맥락, 이상은 직접 업종 기사를 별도 확인합니다. 매매 임계값은 변경하지 않습니다.
[3M 중기] 상태는 당일 방향과 별도입니다. 상태 분류에는 3M·6M·가속도·가격위치를 함께 쓰므로 3M·가속도가 비슷해도 상태는 다를 수 있습니다. 신생 ETF는 실제 관측 이력과 비교 구간을 별도 확인해야 합니다.

업종 | 일간 실제·기준일 | 3M 중기·직전 3M 대비 가속도 | 시장 대비 초과수익 | 해석(추정)
--- | --- | --- | --- | ---
반도체(SOXX) | 사실: 일간 +1.73% · 2026-10-19 [확정 종가] | 3M -7.7% | 미확인: ^GSPC 동일 종가일 일간 수익률 미연결 | 해석(추정): 업종 상승 관측 · 보도 배경 · 업종 관련 보도 · 제목 기준 보도(기사 주장, 인과 기여 미확정): Palantir, Datadog and chip stocks bounce back as Amazon lifts Wall Street [Yahoo Finance · 원문](https://news.google.com/rss/articles/CBMiyAFBVV95cUxPLTJxSmJCOU8tTF9wMHl1cEJ5eXlUQTJEcXhyRjUxQmZoZS1FM0pLd19pUllsQ2p5anZGMkgwU1F5bFFRMnFLUzJaY0RZWldfX0QySjhBWk93YWNSQWxLM3VBZWhwdFVOVVpfZk9YZktkYkVWdjE2WlJvVUFHZ2swYzZzZDcyT1Y5SXFoZExEUmRDXzBtaTlwQWJIMGVCM0pTaU5nRTBERjdTX3dSZkVTZlRoS3ZNVVh4dGlKM2tad2FhMkozc2d5Tg?oc=5)
에너지(XLE) | 사실: 일간 -0.50% · 2026-10-19 [확정 종가] | 3M +10.0% | 미확인: ^GSPC 동일 종가일 일간 수익률 미연결 | 해석(추정): 업종 하락 관측

## 관심 후보 상위 3개
선정 기준: 오늘점검 미보유 목록의 Adj점수 상위 3개. 개별 신호 품질과 시장·종목 실행 게이트는 분리 표시하며 매수 허용 목록이 아닙니다.
S/A 등급과 추세훼손 보류는 함께 표시될 수 있습니다. 품질 등급이 시장·추세·가격·비중 게이트를 해제하지 않습니다. 수치 해제 조건·진입가·손절·목표·제안비중이 입력에 없으면 이 보고서에서 생성하지 않습니다.

후보·개별 신호·실행 상태 | 게이트 근거 | 해제 조건
--- | --- | ---
Datadog(DDOG) · 개별 신호 등급 미제공, 게이트로 보류(방어우선) | 방어우선: 추가매수 보류 | 구체 해제 조건 미제공: 상세 게이트 근거 재확인
원익홀딩스(030530.KS) · 개별 신호 등급 미제공, 게이트로 보류(데이터확인) | 데이터확인: 판단 보류 | 구체 해제 조건 미제공: 상세 게이트 근거 재확인

## 다가오는 일정
- 일정 미연결: 공식 캘린더 수집 실패/자료 미제공. 일정 없음으로 판단하지 않습니다.

## 추가 핵심 뉴스
기준 거래일 마감시황 우선. 이전 거래일의 마감 회고는 제외하며, 마감 후 회고는 사후보도로 표시합니다.
뉴스 분류: ‘추가 핵심 뉴스’는 기준 세션 기사·마감 후 회고, ‘다음 세션 재료’는 별도 분류된 후속 기사입니다. 다음 세션 재료가 비어 있어도 마감 후 회고는 있을 수 있습니다.
출처·중복 제거 기준 통과 34건 · 스토리에서 다룬 6건은 재출력하지 않습니다. 추가 5건 표시.

분류·보도 시각 | 기사·출처 | 제목 해석·한계
--- | --- | ---
뉴스 1 · 마감 후 보도 · 마감 시황 · 2026-10-20 16:00 KST · 마감 후 회고(인과 확정 아님) | 코스피, 3.73% 급락 마감 [뉴시스 · 원문](https://news.google.com/rss/articles/CBMieEFVX3lxTFAxanJoYl84R1hGSDVLU0hCRk96d1pRcjhHVW44dE5HUHh5VVN1TDFwSThITENpR3ZEanRmcXN4SmJhaF9mRlRmWDgzX0c5NFBvVEQ5dERpRERjczE0M3lYdmdGWEZjQWx3NF9ma25aa2hqdldDaW9DYtIBeEFVX3lxTFAxanJoYl84R1hGSDVLU0hCRk96d1pRcjhHVW44dE5HUHh5VVN1TDFwSThITENpR3ZEanRmcXN4SmJhaF9mRlRmWDgzX0c5NFBvVEQ5dERpRERjczE0M3lYdmdGWEZjQWx3NF9ma25aa2hqdldDaW9DYg?oc=5) | 제목 기준·세부 내용 미확인
뉴스 2 · 마감 후 보도 · 마감 시황 · 2026-10-20 16:00 KST · 마감 후 회고(인과 확정 아님) | 코스피, 3.73% 급락하며 5552.74 마감 [뉴시스 · 원문](https://news.google.com/rss/articles/CBMiYEFVX3lxTFBTX2RSNzNjQWJLcExsMGo2VWQ5Ym41ZUtRYW42MHRHMVNFYXpqakIzYlptdFE2a3JTcFpydnVHV1BydjUtVkV3V3NDZTNhQXZRWTV5Yk1ZR2hxbHZ2ZHhjbA?oc=5) | 제목 기준·세부 내용 미확인
뉴스 3 · 마감 후 보도 · 시장 · 2026-10-20 15:58 KST · 마감 후 회고(인과 확정 아님) | [증시-마감] 亞증시에서 코스피만 '급락'…5,500선 후퇴 [연합인포맥스 · 원문](https://news.google.com/rss/articles/CBMicEFVX3lxTE5PQVJ5cFd5R0hvZ3p4c2RzN2thVldMUHdRTWJKNDJOdWFNSFNxUmduV1JyM09lWlZjNmZLaFVqNS1sVVYzaks3ZzIwd3JlU0owT0c4VW5sdDVuYkphZENfd05KRHFQZWlMVzFjUGR3VjE?oc=5) | 제목 기준·세부 내용 미확인
뉴스 4 · 마감 후 보도 · 시장 · 2026-10-20 15:42 KST · 마감 후 회고(인과 확정 아님) | 코스피, 3.73% 내린 5552.74 마감 [서울경제TV · 원문](https://news.google.com/rss/articles/CBMiZEFVX3lxTFByeEdnNWtycFZhYlpFbUhSaWpKOUIzVzZCdnNHeHphNDRneGY1UTRJSDVQVGtzWDRldDNaaWpsWUc4OWk4OUFEOG1qcDVEWGNpNGlNRmN3c2JVWmYtTEtYSHJSeUc?oc=5) | 제목 기준·세부 내용 미확인
뉴스 5 · 마감 후 보도 · 시장 · 2026-10-20 15:36 KST · 마감 후 회고(인과 확정 아님) | 코스피, 3.73% 내린 5,552.74 마감…코스닥도 3%대 하락 [연합뉴스TV · 원문](https://news.google.com/rss/articles/CBMiZ0FVX3lxTE9TbU42SVV3aVBMWW1UdHpsV2tUdDhDUUoxYnlqZHhFS1dIZlRyWk9DSGlucko3amZCRnFoaGNmaWFzUXRiWGk1N0lLa3AtWU1rTERyVXBlczg5MEl3N0w4M0tsMmcxU2M?oc=5) | 제목 기준·세부 내용 미확인

가격·거래량 흐름은 실제 자금 유입액이 아닙니다. 가속도는 최근 3개월 수익률과 직전 3개월 수익률 차이(%p), 다이버전스는 가격과 흐름 지표 방향이 엇갈리는 상태입니다.

## 판정 이력 비교
비교 기준 | 이전 기준일·시각 | 대상 | 비교 | 미비교 | 변경
--- | --- | --- | --- | --- | ---
이전 거래일 | 미국 2026-10-16 / 한국 2026-10-19 | 보유 1개 | 1 | 0 | 0개
이전 거래일 | 미국 2026-10-16 / 한국 2026-10-19 | 관심·미보유 2개 | 2 | 0 | 2개
같은 거래일 직전 생성 | 2026-10-20 23:48 KST | 보유 1개 | 1 | 0 | 0개
같은 거래일 직전 생성 | 2026-10-20 23:48 KST | 관심·미보유 2개 | 2 | 0 | 2개

**판정·사유 변화**
종목 | 변경 항목 | 이전 | 현재 | 비교 기준
--- | --- | --- | --- | ---
Datadog(DDOG) | 사유 | 개별 위험사유 없음 | 가격급락 | 이전 거래일 · 같은 거래일 직전 생성
원익홀딩스(030530.KS) | 판정·게이트 | 방어우선: 추가매수 보류 | 데이터확인: 판단 보류 | 이전 거래일 · 같은 거래일 직전 생성


## 다음 세션 재료
- 출처·시각 기준을 통과한 마감 후 기사 없음/미수집

## 다른 시장/다른 날짜 맥락
한국·미국 업종의 해당 종가 원인으로 연결하지 않은 별도 보도입니다.
- ASIA · 2026-10-20 12:20 KST · [Yahoo Finance · Asian shares mostly decline after AI stocks lead a rebound on Wall Street](https://news.google.com/rss/articles/CBMipAFBVV95cUxNRmRlNDBpRTFtbDNMQ2pHRkEyUnJhVkJONmNzT18tSWZ6UGVCWHotTFdFU3EzTU5id3RjZGhoVTI5cFdUV1FxLXNNdTduXzRWWHIyZ2p2dEgycFZnRXVvOUtMcWJSVWVrZ3NZcHp0T3VHa1l5el9OVXdIZlpRTWo0MXFYaVR5dDh3RDNWU2F5aDgxVXlhZ0U2OHhUZl9vSmVUekhsaA?oc=5)
- JP · 2026-10-19 17:38 KST · [뉴시스 · 日증시, AI 투자 불안에 혼조 마감…닛케이 0.62%↓](https://news.google.com/rss/articles/CBMieEFVX3lxTE5VNjNGWTdLQy1hT1BMSmRnSmlfcDhKV3dacFBIV1lDZGw4WC1QNXFCM0VjYlk1MV9kQ0hGek5INmFyRjBfVzhoZG5uaDRMUDUtekUtM1RRVGN3bXNNS19TblhPX0l5bG1BME5kSWlMQ1RTQ0V6WW1xN9IBeEFVX3lxTE5VNjNGWTdLQy1hT1BMSmRnSmlfcDhKV3dacFBIV1lDZGw4WC1QNXFCM0VjYlk1MV9kQ0hGek5INmFyRjBfVzhoZG5uaDRMUDUtekUtM1RRVGN3bXNNS19TblhPX0l5bG1BME5kSWlMQ1RTQ0V6WW1xNw?oc=5)

## 매크로 수치 근거
기본 18 10Y 금리 +24 유가 +18 = 60 (0~100 범위 적용)

지표 | 수준 | 1개월 변화 | 비교 기준일 → 종가 기준일 | 상태 | 스트레스 기여
--- | --- | --- | --- | --- | ---
10Y 금리 | 5.14 | +2.76% | 미수집 → 2026-10-19 | 수준 경고 · 상승 부담 | +24
WTI 선물(CL=F) | 103.66 | +3.35% | 미수집 → 2026-10-19 | 수준 경고 · 상승 부담 | +18

현재 WTI 103.66달러: 100달러 이상 수준 경고 → 유가 기여 +18점. 기존 산식·매매 임계값 유지.
스트레스 변화: 이전 매크로 스냅샷 없음(변화 원인 추정 안 함).

## 스타일 비교
성장 [] / 방어 []
미국 기준일 미제공 · 종가/장중 구분 미확인(기존 저장 자료)
각 스타일 독립 노출 최소 2개 미충족: 스타일 우열 판단 보류

## 기존 점검 · 중기 흐름 참고
오늘의 전략: 오늘점검 게이트 실행가능 0개. 중기 순위는 별도 관찰자료이며 게이트를 우회하지 않습니다.
- 돈흐름·미국 섹터: 비교 가능한 중기 자료 미연결
- 국내 섹터: 비교 가능한 중기 자료 미연결
- 글로벌 ETF: 비교 가능한 중기 자료 미연결
- 테마: 비교 가능한 중기 자료 미연결
해제 기준: 비중은 목표 범위 복귀, 시장방어는 해당 시장 게이트 해제, 추세는 일봉·주봉 훼손 해소 후 재계산. 가격·손익비·과열 조건도 함께 통과해야 합니다.

데이터 누락:
- 공식 경제지표 발표치·예상·이전
- 향후 7일 확정 일정 미연결
- 거래일 정렬 매크로: MOVE, VIX, 환율

---
빌드: 기준커밋 095c795625e0 · 로드 소스 bffa82918a3aa928 · 실행 C:\Users\82amf\OneDrive\바탕 화면\주식\my-stock-lab\scripts\generate_report_readability_sample.py · 렌더 C:\Users\82amf\OneDrive\바탕 화면\주식\my-stock-lab\stock_lab_core\market_memo.py · 생성ID d336b0b32b53 · 실제 생성시각 2026-10-20T16:26:52+00:00 · 점검 측정ID 미연결 (시각 미확보)