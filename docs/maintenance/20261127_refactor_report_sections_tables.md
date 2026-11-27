# #19 분리 3~6단계: report_sections의 남은 표 4개 (2026-11-27)

사용자 작업 순서(11-26 21:18 KST) 4번 "필요한 코드 리팩토링"의 첫 묶음. 한 블록씩 그대로 옮겼다.
점수·가중치·게이트·매수 조건·캐시·TTL·문구·순서 변경 없음.

## 무엇을 옮겼나

`stock_lab_core/report_evidence.report_sections` 452줄 → 245줄.

| 단계 | 새 함수 | 담당 | 공유 상태 |
| --- | --- | --- | --- |
| 3 | `_background_candidate_lines(synthesis, news, sessions, used_story_news)` | "보도상 배경 후보" 표(아직 인용되지 않은 배경·원인 기사) | 표에 넣은 기사 키를 `used_story_news`에 추가(원래와 같은 집합 객체) |
| 4 | `_economic_release_lines(context, releases, kr_close, kr, now, missing)` | "## 경제지표" 표, 발표 메모(수출 검산·소매판매 진단 등), 컨센서스 연결 줄, 수출 vs 코스피 5D 표 | 결측 사유를 `missing`에 원래 순서로 추가 |
| 5 | `_sector_why_lines(context, news, flow_rows, observations, live, states, now)` | "## 업종별 왜" 표(상·하위·핵심 업종, 레버리지 대용 제외) | 없음 |
| 6 | `_watch_candidate_lines(summary_rows)` | "## 관심 후보 상위 3개"(미보유 Adj 상위 3, 매수 목록 아님) | 없음 |

- 코드 줄은 그대로 옮기고, 각 함수 안에서 쓰던 지역 import만 함께 옮겼다. `report_sections`에서 더 쓰지 않는 import 이름은 지웠다.
- 보유 종목 영향(`holdings_impact_lines`) 호출 위치는 그대로라 `missing` 순서도 같다.

## 확인 (기준: main `a349e4af`, 같은 컴퓨터·같은 Python 3.13)

| 확인 | main 원본 | 분리본 |
| --- | --- | --- |
| `check_refactor.py --scope all` | 2 실패 / 2,495 통과(알려진 실패 2건: `test_decision_refactor_parity` AST, `test_today_quote_performance` 함수 스냅숏) | 같은 2 실패 / 2,495 통과 |
| 전체 테스트(`pytest tests`) | 22 실패 / 10,200 통과 / 1 건너뜀(알려진 22건, `20261126_known_test_failures.md`) | 같은 22건 실패 목록 / 10,200 통과 |
| 테스트 중 `report_sections` 호출 출력(전체 테스트에서 기록, 호출별 SHA-256) | 129건 | 104건 동일. 나머지 25건(market_memo 테스트, 고정 시각 없이 `생성 HH:MM KST`를 찍음)은 두 실행 시각이 달라서였고, 같은 분에 다시 돌리자 25건 모두 동일 |
| 보고서 관련 23개 파일(468건)에서의 호출 58건 | 기준 | 모두 동일 |
| 고정 합성 입력 5종 × 뉴스 유무(마감 18:10, 미국 장중 23:50, 한국 장중 10:30, 빈 문맥 06:30, 발표·업종 없음 16:00) | 기준 | 10건 바이트 동일 |
| pyflakes | 기존 경고 3개 | 같은 3개, 새 경고 없음 |

- 합성 입력은 테스트가 거치지 않던 분기(전망 기준 다름, 예상대비, 컨센서스 출처, 연준 목표금리, 직전 3개월 평균,
  이상치·검증 메모, 수출 원자료 검산, 소매판매 응답 점검, 컨센서스 키 안내)를 지나도록 만들었다.
- 비교 도구는 `scripts/report_sections_parity/`에 남겼다(기록용 pytest 플러그인과 합성 입력 비교). 다음 분리 때 그대로 쓴다.
- 클라우드 저장소가 얕은 복제라 처음에는 과거 커밋을 읽는 스냅숏 테스트 수백 건이 설정 오류로 실패했다. 전체 이력을 받은 뒤 다시 잰 값이 위 표다.

## 운영 확인

순수 이동이라 다음 배포 뒤 보고서 하나에서 네 블록(보도상 배경 후보·경제지표·업종별 왜·관심 후보 상위 3개)이 이전 형식으로 나오는지 본다.
운영 확인: (병합·재부팅 뒤 기록)

## 다음 후보

`report_sections`에 남은 큰 덩어리는 "오늘의 시장 스토리" 사실 줄(지수·코스닥·다일 맥락·장중·지표·원인 보도, 약 80줄)이다.
`used_story_news` 공유가 많아 한 번 더 나눠야 한다. 그 뒤 ROADMAP 표의 app.py 큰 함수(`calc_scores_and_decision` 473줄,
`render_image_theme_flow_section` 421줄, `build_portfolio_analysis_report` 411줄, `render_entry_execution_plan` 399줄)로 넘어간다.

## 7단계: "오늘의 시장 스토리" 사실 줄 (2026-11-27)

`report_sections` 245줄 → 168줄. 남은 덩어리를 두 함수로 옮겼다(코드 줄 그대로).

| 새 함수 | 담당 | 공유 상태 |
| --- | --- | --- |
| `_market_fact_lines(...)` | 지표 서사 기준·발표일 범위, 참여자 기사, 미국 장중, 보유 반도체 노출, 미국 지수, 코스닥, 한국 다일 맥락, 당일 등락 | 미국 장중 반등 기사 키를 `used_story_news`에 추가 |
| `_story_cause_lines(...)` | 선정 지표, 보도 원인/제목 기사, 한국 맥락 기사, 다음 체크 | 인용 기사 키를 `used_story_news`에, 뉴스가 없으면 "허용 출처 핵심 뉴스"를 `missing`에 추가 |

- 중간에 있던 `releases = records(context.get("economic_releases"))` 재할당은 뒤의 경제지표 표가 쓰므로 `report_sections`에 남겼다(같은 값).
- 확인(기준 main `51c084c5`, 두 트리를 동시에 실행): check_refactor all 2 실패 / 2,495 통과(전후 같은 목록), 전체 테스트 22 실패 / 10,200 통과(같은 목록),
  테스트 중 `report_sections` 출력 129건 모두 동일, 합성 입력 10건 바이트 동일, pyflakes 기존 경고 3개 그대로.
- 운영 확인: (병합·재부팅 뒤 기록. 시장 스토리 아래 사실 줄과 '다음 체크'가 이전 형식인지 본다)

다음: `report_sections`는 이제 블록 호출 순서와 공유 상태 전달이 대부분이라 여기서 멈춘다. 다음은 ROADMAP 표의 app.py 큰 함수 하나의 한 책임.
