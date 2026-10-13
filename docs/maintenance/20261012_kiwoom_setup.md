# 키움 조회 설정

## 이번 연결 범위

- 키움 **REST API**의 `au10001` 토큰과 `ka10001` 국내 주식 기본정보만 호출합니다.
- 밸류 패널에서 Yahoo에 없는 PER/PBR/EPS/BPS를 보완합니다. 재무점수를 다시 더하지 않습니다.
- 계좌, 보유량, 평단, 주문 API는 호출하지 않습니다. 현재가/거래량을 시계열에 합치는 기능도 이번 연결에 포함하지 않습니다.
- 키움 뉴스/AI 요약, 미국 종목, ETF 구성종목, 테마 순위는 아직 연결하지 않았습니다. REST 뉴스 명세를 확인하지 못했으므로 뉴스 제공을 약속하지 않습니다.
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

## 검증 범위

요청 형식, 토큰 재사용, 잘못된 종목 응답 거부, 제한 시간, 오류 응답, 비밀값 비노출을 모의 응답으로 검사했습니다. 사용자 키로 실제 인증하지 않았습니다. 실제 값 확보 여부는 배포 후 확인해야 합니다.

## 공식 근거

- 인증 필드: https://openapi.kiwoom.com/guide/apiguide
- IP 및 실전/모의 키 구분: https://openapi.kiwoom.com/intro/serviceInfo
- 국내 기본정보 요청: https://github.com/Kiwoom-Securities/Kiwoom-REST-API/blob/main/examples/국내주식/종목정보/get_domestic_stock_info.py
- 정규화 참고: https://github.com/Kiwoom-Securities/Kiwoom-Plugin/blob/main/tests/test_normalize.py
