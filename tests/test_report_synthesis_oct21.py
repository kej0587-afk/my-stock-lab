"""Same-clock comparisons and evidence-bound explanations, not trade signals."""
from copy import deepcopy
from datetime import datetime, timedelta

import pandas as pd
import pytest

from stock_lab_core.market_memo import build_auto_market_memo
from stock_lab_core.report_evidence import curate_news, korean_headline_reading
from stock_lab_core.report_intraday import intraday_account_metrics, missing_quote_sensitivity
from stock_lab_core.report_holdings import cumulative_holding_comparison
from stock_lab_core.report_quotes import extended_quote_status

NOW = datetime.fromisoformat("2026-10-21T13:23:00+09:00")


def sample():
    live = {ticker: dict(date="2026-10-21", return_=value, as_of=NOW.isoformat())
            for ticker, value in (("^KS11", .026), ("396500.KS", .03), ("0167A0.KS", .0302))}
    for obs in live.values():
        obs["return"] = obs.pop("return_")
    return {"sessions": {"KR": "2026-10-20", "US": "2026-10-20"}, "intraday_prices": live,
            "prices": {"^KS11": {"date": "2026-10-20", "return": -.0373, "previous_return": .0176},
                       "SOXX": {"date": "2026-10-20", "return": -.0038, "previous_return": .0173}},
            "closed_flow_rows": [{"Ticker": t, "기준일": "2026-10-20", "3개월수익률": value}
                                 for t, value in (("SMH", -.0691), ("IGV", .2012))],
            "calendar_events": [{"event": "FOMC meeting", "indicator": "US_FED_RATE_DECISION",
                                 "date": "2026-10-28", "release_at": "2026-10-28", "source": "Federal Reserve"}]}


def test_three_readable_layers_explain_conflicting_directions_without_changing_gate():
    context = sample()
    rows = [{"티커": "0167A0.KS", "보유량": 1, "현재비중": 75, "게이트상태": "방어우선", "최종읽기": "추가매수 보류"},
            {"티커": "RAM", "보유량": 1, "현재비중": 25, "게이트상태": "방어우선", "최종읽기": "추가매수 보류"}]
    before = deepcopy(rows)
    report = build_auto_market_memo(report_context=context, summary_rows=rows, now=NOW)
    headline = report.split("### 중기·최근 거래일·현재 맥락\n", 1)[1].split("\n관측 축 |", 1)[0]
    assert len([line for line in headline.splitlines() if line.startswith("[")]) == 3
    for phrase in ("반도체(SMH)", "소프트웨어(IGV)", "업종 흐름이 갈려", "반등 뒤 하루 되돌림", "중기 추세 회복을 확정할 수 없습니다", "한국 반도체 +3.00%", "SOL AI반도체 +3.02%"):
        assert phrase in headline
    assert "2026-10-29 03:00 KST" in report and "미국 14:00 ET 표준" in report
    assert "영문 제목(번역 미연결)" not in report
    assert rows == before


def test_missing_weight_sensitivity_is_not_a_measured_return():
    rows = [{"티커": "0167A0.KS", "현재비중": 75}, {"티커": "RAM", "현재비중": 25}]
    metrics = intraday_account_metrics(rows, sample()["intraday_prices"], now=NOW)
    assert metrics["missing_weight"] == 25
    assert "±0.75%p" in missing_quote_sensitivity(metrics)
    assert "예측 범위나 실제 장중 수익률이 아닙니다" in missing_quote_sensitivity(metrics)
    assert missing_quote_sensitivity({"total": None, "missing_weight": 100}) == ""


def test_same_publisher_same_us_close_recaps_group_without_merging_other_sessions():
    rows = [dict(title=title, publisher=publisher, published_at=NOW.isoformat(), market="US",
                 session_date="2026-10-20", is_close_wrap=True, link=f"https://example.com/{i}")
            for i, (title, publisher) in enumerate([
                ("[마켓뷰] 메타 실적발표 앞두고 뉴욕증시 혼조 마감…코스피 향방은", "연합뉴스"),
                ("[3분증시] 뉴욕증시, 우량주 강세 속 혼조 마감", "연합뉴스 한민족센터")])]
    grouped = curate_news(rows, now=NOW, session_scoped=True)
    assert len(grouped) == 1 and grouped[0]["duplicate_count"] == 2
    assert grouped[0]["related_articles"][0]["title"] == rows[1]["title"]
    assert len(curate_news([rows[0], dict(rows[1], session_date="2026-10-19")], now=NOW, session_scoped=True)) == 2
    assert korean_headline_reading({"title": "US equities in focus"}) == ""


def test_missing_and_stale_extended_quote_have_different_reasons():
    assert "응답 미수집" in extended_quote_status({}, "RAM", NOW)
    quote = {"symbol": "RAM", "regularMarketTime": datetime.fromisoformat("2026-10-20T16:00:00-04:00").timestamp(),
             "regularMarketPrice": 10, "regularMarketPreviousClose": 10.2,
             "overnightMarketPrice": 10.5, "overnightMarketTime": (NOW - timedelta(minutes=55)).timestamp()}
    assert "55분 경과" in extended_quote_status(quote, "RAM", NOW)


@pytest.mark.parametrize("offset", [0, 5])
def test_alignment_accepts_only_identical_endpoints(offset):
    daily = {"379810.KS": pd.DataFrame({"Close": [100, 101]}, index=pd.to_datetime(["2026-10-19", "2026-10-20"]))}
    futures = pd.DataFrame({"Close": [100, 102]}, index=pd.to_datetime(["2026-10-19T15:25:00+09:00", "2026-10-20T15:25:00+09:00"]) - pd.Timedelta(minutes=offset))
    result = cumulative_holding_comparison({"티커": "379810.KS"}, {"379810.KS": {"date": "2026-10-20"}},
        {"KR": "2026-10-20", "US": "2026-10-19"}, NOW.replace(day=20, hour=17), daily, scenario_frames={"NQ=F": futures})
    if offset:
        assert result.get("error") and "residual_pp" not in result
    else:
        assert result["residual_pp"] == pytest.approx(-1)


def test_input_origin_saved_only_on_fresh_results_and_auto_changes_counted(tmp_path):
    from stock_lab_core.report_history import tag_input_origins, update_report_history
    from stock_lab_core.report_comparison import history_comparison_lines
    frame = pd.DataFrame([{"티커": "005930.KS", "종목명": "삼성전자", "최종읽기": "대기"},
                          {"티커": "TEST", "종목명": "자동 검증", "최종읽기": "대기"}])
    original = frame.copy(deep=True)
    tagged = tag_input_origins(frame, [{"ticker": "005930"}], [{"ticker": "TEST"}])
    assert list(tagged["입력출처"]) == ["등록", "자동"]
    pd.testing.assert_frame_equal(original, frame)
    old = {"KR": "2026-10-19", "US": "2026-10-19"}
    path = tmp_path / "history.json"
    provenance = {"collected_at": NOW.isoformat(), "indices": {"^KS11": {"date": "2026-10-19", "source": "fixture"}}}
    update_report_history(tagged, old, path=path, owner_scope="test", source_provenance=provenance)
    context = update_report_history(tagged, {"KR": "2026-10-20", "US": "2026-10-20"}, path=path, owner_scope="test")
    assert context["previous_summary"][1]["입력출처"] == "자동"
    assert context["previous_source_provenance"] == provenance
    lines = history_comparison_lines(tagged, [{"previous": [], "previous_date": "2026-10-19/2026-10-19",
                                             "current_date": "2026-10-20/2026-10-20"}])
    joined = "\n".join(lines)
    assert "등록: 추가 1개" in joined and "자동: 추가 1개" in joined
    assert "삼성전자" in joined and "자동 검증" not in joined


def test_same_clock_comparison_uses_the_validator_timezone_for_naive_quote_time():
    daily = {"379810.KS": pd.DataFrame({"Close": [100, 100]}, index=pd.to_datetime(["2026-10-19", "2026-10-20"]))}
    index = pd.to_datetime(["2026-10-20T15:25:00+09:00", "2026-10-21T13:15:00+09:00"])
    frames = {"NQ=F": pd.DataFrame({"Close": [100, 102]}, index=index),
              "379810.KS": pd.DataFrame({"Close": [100, 101]}, index=index)}
    live = {"379810.KS": {"date": "2026-10-21", "as_of": "2026-10-21T13:23:00", "return": .01}}
    result = cumulative_holding_comparison({"티커": "379810.KS"}, {}, {"KR": "2026-10-20"}, NOW, daily,
                                          intraday_prices=live, scenario_frames=frames)
    assert result["as_of"] == "2026-10-21T13:20:00+09:00"
    assert result["residual_pp"] == pytest.approx(-1)


def test_incomplete_fixed_macro_is_labeled_partial_and_never_compared_as_relief():
    from stock_lab_core.report_presentation import macro_change
    current = {"유가": {"val": 99, "chg": None, "as_of": "2026-10-20", "kind": "fixed_asof_reference"}}
    previous = {"유가": dict(current["유가"], val=101, chg=20)}
    assert "기준값 미연결로 비교 보류" in macro_change(previous, current)
    report = build_auto_market_memo(report_context={**sample(), "macro_data": current}, now=NOW)
    assert "보고서 매크로 스트레스 부분합" in report
    assert "점수 하락을 위험 완화로 해석하지 않음" in report
