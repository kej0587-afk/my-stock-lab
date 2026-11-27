# DART 재부팅 후 기업코드 캐시

## 범위

`earnings_filing_sources`의 기업코드 준비를 `earnings_dart_directory`로 분리했다.
기존 메모리 기업코드 캐시의 1일 수명을 유지하고, Supabase에 이미 보관한 정상 조회
목록이 **원래 조회시각부터 1일 미만**이면 재부팅 후에도 재사용한다.
캐시를 읽었다고 저장시각을 새로 쓰거나 유효기간을 연장하지 않는다.

공시 목록 10분/실패 90초, 접수번호별 실제 재무제표 1일, 수집 예산 24초,
재시도/HTTP 시간 제한, 기존 7일 전송 장애 대체 목록은 그대로다.
분기값/누적값/발표일/접수일, 투자판정·월적립·L3는 변경하지 않았다.

## 안전 조건

- 저장 해시/출처/형식/시각 검증을 통과한 정상 목록만 사용한다. 동봉 파일은 fresh 캐시가 아니다.
- 24시간 경계, 미래 시각, 손상, 저장소 장애는 공식 조회 경로로 돌아간다.
- 프로세스 캐시 안에 들어간 보관 목록도 원래 만료시각에 다시 조회한다.
- 새 종목이 목록에 없으면 기존 1일 캐시처럼 미등록으로 표시한다. 기업코드를 추정하지 않는다.
- 기업코드는 공개 식별자 캐시다. 실제 공시 요청은 사용자 DART 키로 실행하며 인증 오류를 숨기지 않는다.
- `official_cache`는 정상 캐시, `official_snapshot`은 전송 장애 후 대체 목록이다. 보고서 문구를 구분한다.

## 검증

- 관련 139개 테스트 통과(6.36초): 재부팅 복원, 원래 만료시각, 변조/미래/결측/저장소 장애,
  인증 오류, 신규 종목, 기존 재시도·예산, 분기/누적 실제치.
- 동일 고정 응답에서 events/results 전체 동일. 공시 목록·회사 확인·재무제표 요청 3회는 동일,
  기업코드 ZIP 요청만 1회에서 0회로 줄었다. 외부 실측 성능 수치가 아닌 요청 경로 검증이다.
- report 선택 회귀 208개 통과(46.796초), 기준 파일 재생성 없음.
- 기존 cold 운영 측정: 회사코드 준비 10.546초, 시황 122.100초, 한국 실제치 14개 연결/
  시간 한도 12개. [원인 측정](20261127_dart_cold_audit.md).
- 수정 후 운영 재부팅 검증은 배포 후 기록한다. 단일 전후 값은 2~3회 평균 개선율로 주장하지 않는다.

## 재실행

지원 의존성(`requirements.txt`, pandas <3/numpy <2) 환경에서:

```powershell
python -m pytest -q tests/test_dart_directory_fresh_cache.py tests/test_dart_corporate_store.py tests/test_dart_corporate_codes.py tests/test_earnings_filing_discovery.py tests/test_earnings_dart_financials.py
python scripts/check_refactor.py --scope report
```

운영 JSON은 개인정보가 있어 Git에 넣지 않는다. 원격 요청 수·캐시 출처·실제치 연결 수·시간 한도와
실행 시간을 함께 비교하고, 시황 전체의 다른 공식자료/시세/이력 시간과 구분한다.
