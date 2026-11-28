from copy import deepcopy
import socket
from unittest.mock import MagicMock

import pandas as pd
import pytest

from stock_lab_core.today_overview import action_columns, overview_counts, classify_review_flags, sector_observation_rows, render_overview


@pytest.mark.parametrize("technical,rr", [("강한 분할추매", .19), ("100% 적립", 1.36), ("200% 집중", 2.)])
def test_positive_technical_message_does_not_override_market_defense(technical, rr):
    row = {"티커": "EXAMPLE", "게이트상태": "방어우선", "게이트근거": "시장방어: 신규매수 중단",
           "🔥기술적 타점": technical, "R/R": rr, "후보점수": 88, "부족액": 1000}
    before = deepcopy(row)
    shown = action_columns(row)
    assert shown["오늘 행동"] == "실행 보류"
    assert shown["기술적 타점"] == technical
    assert shown["보류 사유"] == row["게이트근거"]
    assert shown["R/R"] == rr and row == before


def test_candidate_gate_is_not_final_permission():
    assert "최종 체크 전" in action_columns({"게이트상태": "실행가능"})["오늘 행동"]


def test_unique_count_and_hard_subset_are_not_added_twice():
    frame = pd.DataFrame({"티커": [f"X{i}" for i in range(104)],
                          "게이트상태": ["방어우선"]*102 + ["데이터확인"]*2})
    hard = pd.Series([True]*2 + [False]*102)
    result = overview_counts(frame, hard)
    assert result == {"전체":104, "방어우선":102, "데이터확인":2, "실행가능":0, "기타대기":0, "하드차단":2, "중복종목":0}
    duplicate = pd.concat([frame, frame.iloc[[0]]], ignore_index=True)
    assert overview_counts(duplicate)["전체"] == 104
    assert overview_counts(duplicate)["중복종목"] == 1


def test_conflicting_duplicate_gate_is_reported_not_promoted():
    frame = pd.DataFrame([{"티커":"X", "게이트상태":"실행가능"}, {"티커":"X", "게이트상태":"방어우선"}])
    assert overview_counts(frame)["데이터확인"] == 1
    assert overview_counts(frame)["실행가능"] == 0


def test_flags_separate_expected_differences_from_actual_data_failure():
    flags = pd.DataFrame([
        {"문제":"종목 판단 실패", "등급":"주의"},
        {"문제":"파킹자산 · 종목점검 제외", "등급":"제외"},
        {"문제":"돈흐름 강세와 실행 방어 동시 존재", "등급":"참고"},
        {"문제":"돈흐름 후보가 오늘점검에 없음", "등급":"참고"},
        {"문제":"돈흐름 강세와 실행 방어 동시 존재", "등급":"주의"},
    ])
    result = classify_review_flags(flags)
    assert result["확인 구분"].tolist() == ["자료·매칭 확인 필요", "의도된 제외", "후보는 강하지만 실행은 보류", "점검 대상 범위 차이", "자료·매칭 확인 필요"]
    pd.testing.assert_frame_equal(result, classify_review_flags(result))


def test_sector_observation_and_execution_stay_separate_without_network(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", lambda *args: pytest.fail("Display must reuse results"))
    frame = pd.DataFrame([{"티커":"BRK.B", "종목명":"버크셔해서웨이", "게이트상태":"데이터확인", "게이트근거":"일봉 이력 없음"}])
    cards = [{"market":m,"rank":1,"title":"금융","total":7.1,"verdict":"후보권","representatives":"버크셔해서웨이"} for m in ("한국","미국")]
    original = frame.copy(deep=True)
    result = sector_observation_rows(cards,frame)
    assert "실행 보류" not in result.iloc[0]["종목 실행 상태"]
    assert "일봉 이력 없음" in result.iloc[1]["종목 실행 상태"]
    assert result.iloc[1]["기존 점수"] == 7.1
    assert result["시장 차단만 해제"].str.contains("미검증").all()
    render_overview(MagicMock(),frame,cards,pd.DataFrame())
    pd.testing.assert_frame_equal(frame,original)


def test_designated_parking_is_not_a_missing_holding_but_unknown_equity_is(app_module):
    summary = pd.DataFrame([{"티커":"EXAMPLE", "게이트상태":"방어우선"}])
    holdings = pd.DataFrame([{"티커":"SGOV","자산명":"Parking","bucket":"reserve"},
                             {"티커":"UNKNOWN","자산명":"Check","bucket":"swing"}])
    flags = app_module.build_today_review_flags_df(summary,holdings)
    parking = flags[flags["티커"].eq("SGOV")]
    assert list(parking["문제"]) == ["파킹자산 · 종목점검 제외"]
    assert parking["확인 구분"].eq("의도된 제외").all()
    assert "보유자산이 오늘점검에 없음" in set(flags.loc[flags["티커"].eq("UNKNOWN"),"문제"])
    holdings.loc[0,"bucket"] = "swing"
    flags = app_module.build_today_review_flags_df(summary,holdings)
    assert "보유자산이 오늘점검에 없음" in set(flags.loc[flags["티커"].eq("SGOV"),"문제"])


def test_designated_parking_in_watchlist_is_not_reintroduced(app_module, monkeypatch):
    monkeypatch.setattr(app_module, "holdings_table", pd.DataFrame([
        {"티커":"SGOV","자산명":"Parking","bucket":"reserve","보유량":5,"현재비중":3}]))
    items = [{"ticker":"SGOV","bucket":"swing","name":"Parking"}, {"ticker":"MSFT","bucket":"swing","name":"Example"}]
    assert [row["ticker"] for row in app_module.build_today_queue_items(items)] == ["MSFT"]


def test_detail_csv_columns_put_action_before_technical():
    from stock_lab_core.today_queue_view import DETAIL_COLUMNS
    assert DETAIL_COLUMNS.index("현재실행안내") < DETAIL_COLUMNS.index("🔥기술적 타점")
    assert len(DETAIL_COLUMNS) == len(set(DETAIL_COLUMNS))


def test_only_visible_unambiguous_capture_is_joined():
    frame = pd.DataFrame([{'티커':'BRK.B','종목명':'BRK.B','게이트상태':'데이터확인'},
                          {'티커':'MSFT','종목명':'Microsoft','게이트상태':'방어우선'}])
    card = {'market':'미국','representatives':'Microsoft',
            'representative_links':[{'name':'버크셔해서웨이','ticker':'BRK-B'}]}
    result = sector_observation_rows([card],frame).iloc[0]['종목 실행 상태']
    assert 'Microsoft: 실행 보류' in result and 'BRK' not in result
    card['representatives'] = '버크셔해서웨이'
    assert '버크셔해서웨이: 실행 보류' in sector_observation_rows([card],frame).iloc[0]['종목 실행 상태']
    card['market'] = '한국'
    assert '시장 불일치' in sector_observation_rows([card],frame).iloc[0]['종목 실행 상태']
