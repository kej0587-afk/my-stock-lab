# 공시 탐색 구간의 고정 입력 대조와 운영 계측

시작 커밋 `05202ad1`, 깨끗한 main. 대상은 `earnings_filing_discovery`
23.260초 구간이다. 이전 계측의 self 시간은 작업 스레드 완료 대기를 포함하므로
CPU 계산 23초로 해석할 수 없다. HTTP76회/활성 벽시간12.136초와 직접 빼서
나머지를 파싱 시간으로 단정할 수도 없다.

## 이번 변경

요청을 줄이기 전에 실제 중복 여부와 대기를 구분하도록 계측만 추가했다.
종목 중복 제거, 3개 worker, SEC 요청 간격0.2초, 전체수집24초,
성공캐시600초/실패90초/기업식별자86400초, 공급사 우선순위·파서·점수는 유지한다.
기존 성공/실패 반환값과 요청 인자도 유지한다.

- SEC/DART 식별자 준비, worker 실행/완료 대기, SEC 제한 대기,
  HTTP get/스트리밍 본문, JSON/공시/실적 해석 시간을 분리한다.
- 실제 `get` 호출 시 공급사별 attempt/unique_identity/duplicate_identity를 센다.
  URL과 모든 요청 인자가 같은 경우만 중복으로 센다. 재시도도 그대로 실행한다.
  진단에는 집계값만 남기며 URL·인증키·헤더·종목별 식별자는 저장하지 않는다.
- worker 시작 전 큐 대기는 마이크로초 합계와 collection별 최대값 합계로 기록한다.
  `collections=1`일 때만 max_sum이 해당 실행의 최장 큐 대기다.
  모든 worker의 대기 합계를 전체 벽시간에 더하면 안 된다.
- 캐시 namespace별 hit/failure_hit/miss는 HTTP 건수와 별개다.
  DART 기업코드 ZIP의 get은 본문까지 포함하고, stream=True 요청만 별도
  http_body가 있으므로 두 종류를 혼동하지 않는다. 중첩 구간은 합산하지 않는다.
- 새 계측 모듈을 운영 코드 일치 검사에도 등록했다. 금융 결과에 새 필드를
  붙이지 않으며 정상 보고서 문구나 데이터 범위를 바꾸지 않는다.

## 고정 입력 검증

- 기존 SEC/DART/보고서와 신규 계측 테스트 **142 통과 /14.70초**.
  다중 collection 큐 최대값 명칭을 명확히 한 후 신규5건 재확인 통과.
- 선택 보고서 gate 전208통과/51.673초 (`report_x40bxczj`),
  최종208통과/46.529초 (`report_szghqu6k`). golden 재생성 없음.
- 수정 전 수집기와 같은 합성 SEC/DART 입력·시각·캐시 순서를 재생했다.
  cold/warm, TTL 직전/만료, 과거 기준시각, 실패캐시 직전/만료를 포함한
  **수집 결과9건 완전 일치**, 모든 요청 인자 multiset도 일치. 네트워크0회.
  이 검사는 동등성 검사이며 실제 속도 개선 실험이 아니다.
- 비밀값이 계측 JSON에 나오지 않는지, 같은 요청도 실제 재시도하는지,
  캐시적중을 새 요청으로 세지 않는지와 worker 측정 문맥 전달을 검사했다.

## 운영 검증

계측본 배포·직접 Reboot 후 자동 시황 완료본에서 위 분해를 확인할 예정이다.
실제 동일 요청이 없다면 재사용 최적화를 추가하지 않는다.

비공개 근거는 ignored `cache/earnings_discovery_20261121/`에 보존:
`earnings_filing_sources_before.py`, `earnings_collection_before.py`,
`fixed_replay.py`, `fixed_replay.json`. 개인 자료는 Git 제외.
