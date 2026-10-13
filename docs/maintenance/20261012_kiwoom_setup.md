# 키움 조회 설정

## 이번 연결 범위

- 키움 **REST API**의 `au10001` 토큰과 `ka10001` 국내 주식 기본정보를 사용합니다.
- 밸류 패널에서 Yahoo에 없는 PER/PBR/EPS/BPS를 보완합니다. 재무점수를 다시 더하지 않습니다.
- 계좌, 보유량, 평단, 주문 API는 호출하지 않습니다. 현재가/거래량을 시계열에 합치는 기능도 이번 연결에 포함하지 않습니다.
- 10/13 추가: `ka10032` 거래대금 상위, `ka90001` 테마 그룹, `ka90002` 선택 테마 구성종목, `ka10051` KOSPI/KOSDAQ 업종별 투자자 순매수를 연결했습니다.
- 돈흐름 레이더의 **키움 시장근거** 탭, 오늘점검 브리핑의 **키움 거래대금·테마·업종 수급**에서 조회합니다. 첫 조회는 버튼으로 시작하며, 이후 정상 응답은 3분, 실패 응답은 60초간 보관합니다. 선택 구성종목과 업종 수급도 요청 시에만 조회합니다.
- 첫 페이지만 조회하며 표시 행 수와 후속 페이지 유무를 표시합니다. 조회시각은 시세 기준시각이 아닙니다. KRX 기준이며 NXT/통합 거래대금으로 표시하지 않습니다.
- 거래대금(백만원), 거래량(주), 순매수(억원)를 구분합니다. 관찰 표는 기존 매수 게이트를 우회하지 않으며 관심종목을 자동 추가하지 않습니다.
- 공식 저장소에는 미국주식 조회도 있지만 이번 앱에는 아직 연결하지 않았습니다. 키움 뉴스/AI 요약, ETF 구성종목 역시 미연결입니다. 공개 REST 명세에서 뉴스 API를 확인하지 못했으므로 뉴스 제공을 약속하지 않습니다. 종목 뉴스 버튼은 기존 RSS 검색을 사용합니다.
- 모의 응답은 실제 밸류 판정에 혼합하지 않습니다. 기간이 불명확한 매출/순이익으로 TTM PER/PSR을 추정하지 않습니다.

## Streamlit Cloud

Manage app > Settings > Secrets에서 기존 설정을 지우지 말고 아래 블록을 추가합니다. 같은 `[kiwoom]` 블록이 있으면 그 블록만 수정합니다.

```toml
[kiwoom]
enabled = true
appkey = "키움 REST App Key"
secretkey = "키움 REST App Secret"
environment = "real"
```

예시 파일에는 실제 값을 넣지 마세요. 키를 바꾼 뒤 앱을 재시작해야 메모리에 남은 클라이언트/토큰도 바뀝니다. 체험모드는 키를 읽지 않습니다.

키움은 허용 IP를 요구합니다. Cloud에서 실행한다면 집 PC가 아니라 **앱 서버의 외부 접속 IP**가 인증에 허용돼야 합니다. 키만 입력했다고 Cloud 연결을 보장할 수 없습니다. IP/상품 권한 문제는 데이터 조회 실패로 남기고 기존 공급자를 계속 사용합니다.

## CLI와 앱 연동의 차이

공식 `kwcli`는 같은 API를 터미널/AI 도구에서 호출하는 방법입니다. 이 앱은 REST를 직접 호출하므로 CLI 설치나 별도의 키 재입력이 필요하지 않습니다. 공식 CLI/샘플의 Python 3.13+ 요건 때문에 현재 앱의 Python 3.11을 함께 올리지 않았습니다. 계좌/주문 권한을 가진 범용 CLI를 앱 안에서 실행하지 않습니다.

## 검증 범위

요청 형식, 토큰 재사용, 잘못된 종목 응답 거부, 제한 시간, 오류 응답, 비밀값 비노출을 모의 응답으로 검사했습니다. 사용자 키로 실제 인증하지 않았습니다. 실제 값 확보 여부는 배포 후 확인해야 합니다.

## 공식 근거

- 인증 필드: https://openapi.kiwoom.com/guide/apiguide
- IP 및 실전/모의 키 구분: https://openapi.kiwoom.com/intro/serviceInfo
- 국내 기본정보 요청: https://github.com/Kiwoom-Securities/Kiwoom-REST-API/blob/main/examples/국내주식/종목정보/get_domestic_stock_info.py
- 공식 전체 API 명세: https://github.com/Kiwoom-Securities/Kiwoom-REST-API/blob/main/kiwoom/_data/kiwoom_api_spec.json
- 정규화 참고: https://github.com/Kiwoom-Securities/Kiwoom-Plugin/blob/main/tests/test_normalize.py
