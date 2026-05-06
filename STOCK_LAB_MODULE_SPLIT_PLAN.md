# Stock Lab Module Split Plan

이 문서는 `app.py`를 바로 크게 쪼개기 전에, 안전하게 나눌 경계와 순서를 정리한 작업 지침입니다.

## 목표

- 화면 동작과 Supabase 데이터를 유지하면서 `app.py`의 책임을 조금씩 분리합니다.
- 한 번에 큰 리팩터링을 하지 않고, 작은 단위로 분리한 뒤 매번 문법 확인과 앱 확인을 합니다.
- 인증, DB 저장, 점수계산처럼 위험도가 높은 영역은 마지막 단계로 둡니다.

## 권장 경계

| 모듈 | 역할 | 분리 우선순위 |
|---|---|---|
| `stock_lab_core.formatters` | 통화/숫자/불리언/티커 정규화, HTML escape, DataFrame 보정 | 1 |
| `stock_lab_core.config` | 컬럼 목록, 기본 watchlist, 벤치마크 티커, 점수 키 같은 상수 | 2 |
| `stock_lab_core.backup` | CSV 백업/복구, ZIP 생성, 업로드 파일 파싱 | 3 |
| `stock_lab_core.news` | 뉴스 검색어 생성, RSS 파싱, 뉴스 품질 필터 | 4 |
| `stock_lab_core.prices` | yfinance 가격 로드, 최신가 갱신, 가격 캐시 정리 | 5 |
| `stock_lab_core.portfolio` | 보유자산 표, 요약 지표, 월별 기록/수익률 계산 | 6 |
| `stock_lab_core.ui_asset` | 자산 현황/포트폴리오 분석 탭 렌더링 | 7 |
| `stock_lab_core.ui_analysis` | 정밀관측소, 전광판, 시나리오/단기 흐름 탭 렌더링 | 8 |
| `stock_lab_core.storage` | Supabase load/save, owner_email 범위 보장 | 후순위 |
| `stock_lab_core.auth` | Google/password 인증, logout, secrets 처리 | 후순위 |
| `stock_lab_core.scoring` | 기술점수, 재무점수, 판정 문구, SMC 계산 | 후순위 |

## 진행 순서

1. 순수 포맷/정규화 함수부터 분리합니다.
2. 상수/컬럼 정의를 분리하되, 기존 이름은 유지해서 호출부 변경을 최소화합니다.
3. 백업/CSV 함수처럼 입출력이 명확한 기능을 분리합니다.
4. 뉴스 함수는 품질 개선과 함께 별도 모듈로 이동합니다.
5. 가격 로드와 캐시 정리는 성능 개선 작업과 묶어서 분리합니다.
6. 포트폴리오 계산 함수를 UI에서 떼어냅니다.
7. UI 탭 함수는 마지막에 천천히 나눕니다.
8. DB 저장, 인증, 점수계산은 충분히 안정화된 뒤 별도 유지보수 시간에 진행합니다.

## 작업 규칙

- 한 번의 패치에서는 한 모듈 또는 한 책임만 옮깁니다.
- Supabase 테이블 구조, `owner_email`, 로그인 방식은 모듈 분리 중 변경하지 않습니다.
- 기존 함수명과 반환값을 유지해서 화면 호출부 변경을 줄입니다.
- 매번 `python -m py_compile app.py`로 문법 확인 후 라이브 앱에 반영합니다.
- 라이브 반영 전에는 `app.py.bak_YYYYMMDD_작업명` 백업을 남깁니다.

## 현재 상태

- 1차 분리로 `stock_lab_core.formatters`를 추가했습니다.
- `app.py`의 포맷/정규화/간단 변환 함수 일부는 이 모듈에서 가져오도록 준비했습니다.
- 2차 분리로 `stock_lab_core.config`를 추가하고, 주요 Supabase/스윙 편집 컬럼 목록을 옮겼습니다.
- 3차 분리로 기본 관심종목과 reserve/cash 관련 기본 상수를 `stock_lab_core.config`로 옮겼습니다.
- 4차 분리로 `stock_lab_core.backup`을 추가하고, ZIP 백업 생성/CSV 판별/업로드 파일 수집/복구 이슈 작성 helper를 옮겼습니다.
- 5차 분리로 `stock_lab_core.news`를 추가하고, 뉴스 검색/품질 필터/뉴스 카드/리포트 링크/목표가 패널을 옮겼습니다.
- 6차 분리로 `stock_lab_core.prices`를 추가하고, 일봉 가격/최신가/배치 최신가/가격 캐시 helper를 옮겼습니다.
- 7차 분리로 `stock_lab_core.money_flow`를 추가하고, 돈흐름 ETF 유니버스/가격 다운로드/돈흐름 점수 계산을 옮겼습니다.
- 8차 분리로 `stock_lab_core.portfolio`를 추가하고, 포트폴리오 요약/현금 행/대기자금 요약/보유종목 조회 helper를 옮겼습니다.
- 9차 분리로 월별 투자기록/기간수익률/벤치마크 수익률 계산 helper를 `stock_lab_core.portfolio`로 옮겼습니다.
- 10차 분리 준비로 `build_holdings_table()`의 비중/운용대상/리밸런싱목표비중 후처리를 `apply_holdings_weight_columns()`로 분리했습니다.
- DB, 인증, 점수계산, 저장 로직은 변경하지 않았습니다.
