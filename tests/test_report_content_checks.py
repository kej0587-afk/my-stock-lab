from datetime import datetime
from zoneinfo import ZoneInfo

from stock_lab_core.report_digest import content_checks

NOW = datetime(2026, 11, 24, 15, tzinfo=ZoneInfo("Asia/Seoul"))


def states(context, reading=""):
    return {name: (state, detail) for name, state, detail in content_checks(context, reading, NOW)}


def test_repeated_story_in_market_body_fails_and_other_sections_do_not_count():
    reading = ("## 한국 시황\n\n분야 | 재료 | 확인\na | [x](https://a.example/1)\nb | [y](https://a.example/1)\n"
               "## 주요 기업과 사건\n\n분야 | 재료 | 확인\nc | [z](https://b.example/2)\nd | [z](https://b.example/2)\n")
    state, detail = states({}, reading)["시황 본문 기사 중복"]
    assert state == "실패" and "https://a.example/1" in detail and "b.example" not in detail
    assert states({}, "## 미국 시황\n\n분야 | 재료 | 확인\na | [x](https://a.example/1)\n")["시황 본문 기사 중복"][0] == "통과"


def test_consensus_month_mismatch_fails_and_unlabeled_is_unknown():
    ok = {"indicator": "US_PPI", "period": "2026-10", "forecast": 6.6, "forecast_period": "2026-10"}
    assert states({"economic_releases": [ok]})["컨센서스 대상월"][0] == "통과"
    bad = dict(ok, forecast_period="2026-09")
    state, detail = states({"economic_releases": [ok, bad]})["컨센서스 대상월"]
    assert state == "실패" and "2026-10≠2026-09" in detail
    assert states({"economic_releases": [dict(ok, forecast_period=None)]})["컨센서스 대상월"][0] == "미확인"


def test_future_observation_date_fails():
    good = {"local_indices": {"^N225": {"date": "2026-11-20"}, "^HSI": {}}}
    assert states(good)["관측실·현지 지수 기준일"] == ("통과", "표시 1개 모두 생성일 이후 날짜 없음(완료 일봉)")
    bad = {"observatory_daily": {"EWZ": {"date": "2026-11-25"}}}
    assert states(bad)["관측실·현지 지수 기준일"][0] == "실패"


def test_link_reused_by_another_table_is_not_a_repeat_but_same_sentence_is():
    reading = ("## 한국 시황\n\n발동일 | 시장 | 출처\n--- | --- | ---\n11-24 | 사이드카 | [연합](https://a.example/1)\n\n"
               "분야 | 재료 | 확인\n--- | --- | ---\n시장 | [연합 · 사이드카 발동](https://a.example/1) · 11/24 09:06 KST | 확인\n")
    assert states({}, reading)["시황 본문 기사 중복"][0] == "통과"
    same = "AI 관련 기업들의 주가 거품 논란과 자금조달 부담이 여전하다는 보도"
    reading = ("## 미국 시황\n\n분야 | 재료 | 확인\n--- | --- | ---\n"
               f"반도체 | {same} [연합 · 원문](https://a.example/1) · 11/24 04:09 KST | x\n"
               f"반도체 | {same} [연합 · 원문](https://a.example/2) · 11/24 00:35 KST | x\n")
    state, detail = states({}, reading)["시황 본문 기사 중복"]
    assert state == "실패" and "같은 문장" in detail


def test_title_only_rows_with_shared_boilerplate_are_not_repeats():
    # 2026-11-24 15:07 production: title-only rows differ only inside the link text.
    reading = ("## 한국 시황\n\n분야 | 재료 | 확인\n--- | --- | ---\n"
               "시장 | [연합뉴스 · 코스피 급등에 매수 사이드카 발동](https://a.example/1) (제목 확인·기사 주장) · 11/24 09:06 KST / KR 2026-11-24 장중 관측 | x\n"
               "시장 | [파이낸셜뉴스 · 외국인 순매수 전환](https://a.example/2) (제목 확인·기사 주장) · 11/24 09:08 KST / KR 2026-11-24 장중 관측 | x\n")
    assert states({}, reading)["시황 본문 기사 중복"][0] == "통과"


def test_sector_evidence_table_repeats_are_not_checked():
    reading = ("## 미국 시황\n\n업종 | 사실 | 해석\n--- | --- | ---\n"
               "XLK | 사실: 일간 +3.23% · 2026-11-23 [확정 종가] | [a](https://a.example/1)\n"
               "SOXX | 사실: 일간 +3.23% · 2026-11-23 [확정 종가] | [a](https://a.example/1)\n")
    assert states({}, reading)["시황 본문 기사 중복"][0] == "미확인"
