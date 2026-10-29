"""Offline Kiwoom sector-flow schema and report-link regressions."""

from copy import deepcopy
from datetime import datetime, timedelta

import pytest
from streamlit.testing.v1 import AppTest

from stock_lab_core.kiwoom_market import normalize_market_rows
from stock_lab_core.market_sentiment import sentiment_evidence
from stock_lab_core.report_observation_panel import observation_report_lines


CHECKED = "2026-10-29T10:32:00+09:00"


def snapshot(kind, *, fetched_at=CHECKED, **extra):
    market = "KOSDAQ" if kind == "sector_kosdaq" else "KOSPI"
    result = normalize_market_rows({"inds_netprps": [
        {"inds_cd": "001", "inds_nm": market + " 전체", "frgnr_netprps": "-120.5",
         "orgn_netprps": "+20.5", "ind_netprps": "", "flu_rt": "+2.0"},
        {"inds_cd": "002", "inds_nm": "반도체", "frgnr_netprps": "0", "orgn_netprps": ""},
    ]}, kind)
    return dict(result, fetched_at=fetched_at, asof="", source="Kiwoom REST ka10051",
                is_mock=False, has_more=True, **extra)


def context(evidence):
    return {"quote_checked_at": CHECKED, "market_observation_evidence": evidence}


def flow_rows(result):
    return [row for row in result["rows"] if "순매수" in row["지표"]]


@pytest.mark.parametrize("kind,market", [("sector_kospi", "KOSPI"), ("sector_kosdaq", "KOSDAQ")])
def test_normalized_sector_schema_reaches_report_with_market_and_signed_units(kind, market):
    ctx = context({kind: snapshot(kind)})
    original = deepcopy(ctx)
    result = sentiment_evidence(ctx)
    matched = [row for row in flow_rows(result) if market in row["지표"]]
    assert len(matched) == 2
    assert "-120.5억원" in matched[0]["관측"] and "+0.0억원" in matched[0]["관측"]
    assert "+20.5억원" in matched[1]["관측"]
    assert "반도체" not in matched[1]["관측"]  # Missing is not a zero purchase.
    assert all(row["기준일"] == CHECKED and "전체 합산 아님" in row["범위·한계"] for row in matched)
    report = "\n".join(observation_report_lines(ctx, [], [], datetime.fromisoformat(CHECKED)))
    assert market + " 외국인 순매수" in report and "-120.5억원" in report
    assert ctx == original


def test_each_market_is_separate_and_never_sums_overlapping_sector_totals():
    snapshots = {kind: snapshot(kind) for kind in ("sector_kospi", "sector_kosdaq")}
    result = flow_rows(sentiment_evidence(context(snapshots)))
    assert len(result) == 4
    assert all("-241.0" not in row["관측"] for row in result)
    assert "KOSDAQ" not in result[0]["관측"] and "KOSPI" not in result[2]["관측"]


@pytest.mark.parametrize("age,accepted", [(0, True), (300, True), (301, False), (-1, False), (86400, False)])
def test_freshness_applies_independently_without_relabeling_old_or_future_data(age, accepted):
    at = (datetime.fromisoformat(CHECKED) - timedelta(seconds=age)).isoformat()
    result = flow_rows(sentiment_evidence(context({"sector_kosdaq": snapshot("sector_kosdaq", fetched_at=at)})))
    rows = [row for row in result if "KOSDAQ" in row["지표"]]
    assert len(rows) == 2
    assert all((row["관측"] != "미연결") is accepted for row in rows)
    assert all(row["기준일"] == at for row in rows)
    if age > 300:
        assert all("5분 초과" in row["범위·한계"] for row in rows)
    if age < 0:
        assert all("이후" in row["범위·한계"] for row in rows)


def test_stale_kospi_does_not_hide_fresh_kosdaq_and_mock_never_links():
    old = "2026-10-28T15:00:00+09:00"
    evidence = {"sector_kospi": snapshot("sector_kospi", fetched_at=old),
                "sector_kosdaq": snapshot("sector_kosdaq")}
    result = flow_rows(sentiment_evidence(context(evidence)))
    assert all(row["관측"] == "미연결" for row in result[:2])
    assert all(row["관측"] != "미연결" for row in result[2:])
    evidence["sector_kosdaq"]["is_mock"] = True
    result = flow_rows(sentiment_evidence(context(evidence)))
    assert all(row["관측"] == "미연결" for row in result)
    assert all("모의자료 제외" in row["범위·한계"] for row in result[2:])


@pytest.mark.parametrize("rows", [[], [{"현재가(원)": 70000, "거래대금(백만원)": 1000}],
                                 [{"inds_cd": "001", "frgnr_netprps": "100"}]])
def test_price_turnover_or_raw_provider_rows_are_not_normalized_net_buys(rows):
    snap = snapshot("sector_kosdaq")
    snap["rows"] = rows
    result = flow_rows(sentiment_evidence(context({"sector_kosdaq": snap})))
    assert all(row["관측"] == "미연결" for row in result)
    assert all("순매수 필드" in row["범위·한계"] for row in result if "KOSDAQ" in row["지표"])


def test_other_snapshot_kinds_cannot_be_used_as_sector_flows():
    result = sentiment_evidence(context({"turnover": snapshot("sector_kospi"),
                                         "us_sectors": snapshot("sector_kosdaq")}))
    assert all(row["관측"] == "미연결" for row in flow_rows(result))
    assert all("조회 미실행" in row["범위·한계"] for row in flow_rows(result))


@pytest.mark.parametrize("changed", [{"fetched_at": ""}, {"fetched_at": "not-a-time"},
                                    {"ok": False, "status": "timeout"}])
def test_missing_time_and_provider_failures_are_not_usable(changed):
    snap = snapshot("sector_kosdaq")
    snap.update(changed)
    rows = flow_rows(sentiment_evidence(context({"sector_kosdaq": snap})))
    assert all(row["관측"] == "미연결" for row in rows)


def test_panel_kosdaq_selection_publishes_exact_snapshot_key_used_by_report():
    app = AppTest.from_string('''
import streamlit as st
from stock_lab_core.kiwoom_market import normalize_market_rows
from stock_lab_core.market_evidence_panel import render_market_evidence_panel
from stock_lab_core.market_sentiment import sentiment_evidence

def fetch(kind, theme_code=""):
    st.session_state.setdefault("requests", []).append(kind)
    raw = {"inds_netprps": [{"inds_cd": "001", "inds_nm": "KOSDAQ",
                            "frgnr_netprps": "-12.5", "orgn_netprps": "3.5"}]}
    result = normalize_market_rows(raw, kind) if kind.startswith("sector_") else {"ok": False, "rows": []}
    return dict(result, fetched_at="2026-10-29T01:31:00+00:00", is_mock=False)
fetch.clear = lambda *args: None
render_market_evidence_panel(st, status="ready", fetch_snapshot=fetch, get_news=lambda *args: ([], []),
                             render_news=lambda rows: None, key_prefix="flow_link")
st.session_state["report_evidence"] = sentiment_evidence({
    "quote_checked_at": "2026-10-29T10:32:00+09:00",
    "market_observation_evidence": st.session_state.get("market_observation_evidence", {})})
''').run()
    assert not app.exception
    app.button(key="flow_link_refresh").click().run()
    assert not app.exception
    assert not any(kind.startswith("sector_") for kind in app.session_state["requests"])
    app.radio(key="flow_link_market").set_value("KOSDAQ").run()
    app.button(key="flow_link_flow").click().run()
    assert not app.exception
    assert set(app.session_state["market_observation_evidence"]) == {"sector_kosdaq"}
    rows = flow_rows(app.session_state["report_evidence"])
    assert any("KOSDAQ" in row["지표"] and "-12.5억원" in row["관측"] for row in rows)
    assert all(row["관측"] == "미연결" for row in rows if "KOSPI" in row["지표"])
