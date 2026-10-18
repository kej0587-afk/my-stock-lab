# 경제지표 API 키 설정

키 값은 채팅이나 Git에 올리지 않는다. 이 작업에서는 실제 키를 설정하지 않았다.

## 발급

1. [FRED API 키](https://fred.stlouisfed.org/docs/api/api_key.html): FRED 로그인 후 API 키 발급. `DFEDTARU` 연준 목표금리 상단 조회에 사용.
2. [Census API 키](https://api.census.gov/data/key_signup.html): 이메일로 신청/활성화. MARTS 소매판매 전월비 조회에 사용. 무키 요청이 차단되면 미연결로 표시.
3. [한국은행 ECOS](https://ecos.bok.or.kr/api/): Open API 이용 신청 후 인증키 발급. 소비자물가 총지수와 수출금액의 월별 원자료에서 전년비 계산.

## Streamlit Cloud

해당 앱 Manage App → Settings → Secrets에서 아래 최상위 항목을 추가한다.
기존 `[kiwoom]` 섹션 안에 넣지 않도록, 파일 맨 위의 다른 섹션 선언보다 앞에 넣는다.
실제 발급값이 없으면 빈 항목을 추가하지 않아도 된다.

```toml
FRED_API_KEY = "발급받은 FRED 키"
CENSUS_API_KEY = "발급받은 Census 키"
ECOS_API_KEY = "발급받은 ECOS 키"
```

또는 `[economic]` 섹션 아래 동일한 이름으로 넣을 수 있다. 로컬 환경변수도 동일 이름을 지원한다.
키가 없어도 BLS 물가·고용 수집과 Fed 일정은 별도 키 없이 시도한다.
발표치 API는 컨센서스 공급원이 아니므로 키를 넣어도 예상치가 자동으로 생기지 않는다.
예상 미연결은 이전 대비/직전 3개월 평균을 구분해 보여준다.

## 확인

리포트 생성 후 소매판매/연준 목표금리/한국 물가·수출의 값, 관측월, 단위, 출처를 확인한다.
실패를 0으로 바꾸지 않으며 오류 메시지에는 키나 인증 URL을 포함하지 않는다.
ECOS는 메타데이터의 항목명/단위를 검증한 뒤 수치를 사용한다.
