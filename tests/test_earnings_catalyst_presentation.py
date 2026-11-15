"""Collected evidence stays dated, attributed and separate from trade inputs."""

from copy import deepcopy
from datetime import datetime

import pytest

from stock_lab_core.earnings_pipeline import build_earnings_pipeline
from stock_lab_core import report_earnings
from tests.test_earnings_reconciliation import article, context, event, result, SOURCE


NOW = datetime.fromisoformat("2026-11-06T11:00:00+09:00")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    import requests
    monkeypatch.setattr(requests.sessions.Session, "request",
                        lambda *a, **k: pytest.fail("Rendering must not request data"))


def followup(**changes):
    return article(**dict(dict(title="Alphabet Q3 2026 earnings disappoint on capital expenditure",
                               published_at="2026-11-05T10:00:00-05:00"), **changes))


def current_context():
    return context(earnings_results=[result(checked_at="2026-11-06T10:59:00+09:00")])


def compact(pipeline, market="US"):
    return "\n".join(report_earnings.compact_catalyst_lines(pipeline, market))


def test_comprehensive_catalysts_show_all_issuers_and_revenue_profit_not_only_cash():
    pipeline = build_earnings_pipeline(current_context(), news=[followup()], now=NOW)
    base = deepcopy(pipeline["packets"][0])
    pipeline["packets"] = [dict(deepcopy(base), ticker=f"FIX{i}", name=f"Fixture {i}") for i in range(7)]
    before = deepcopy(pipeline)
    legacy = compact(pipeline)
    full = "\n".join(report_earnings.compact_catalyst_lines(pipeline, "US", limit=None))
    assert legacy.count("**Fixture") == 4
    assert full.count("**Fixture") == 7
    for value in ("Revenue: USD 100", "GAAP EPS 2", "CAPEX: USD 50", "FCF: USD -10"):
        assert value in full
    assert pipeline == before


def test_same_period_followup_keeps_release_date_and_metrics_but_refreshes_evidence():
    data, row = current_context(), followup()
    before = deepcopy(data)
    baseline = build_earnings_pipeline(data, now=NOW)
    pipeline = build_earnings_pipeline(data, news=[row], now=NOW)
    packet, = pipeline["highlights"]
    assert packet["date"] == "2026-10-28" and packet["date_basis"] == "공식 발표일"
    assert packet["latest_evidence_at"] == "2026-11-06T00:00:00+09:00"
    assert packet["latest_evidence_basis"] == "보도일·발표일 아님"
    assert packet["metrics"] == baseline["packets"][0]["metrics"]
    assert pipeline["events"] == baseline["events"] and data == before
    for rendered in ("\n".join(report_earnings.earnings_story_lines(pipeline)), compact(pipeline)):
        assert "2026-10-28" in rendered and "2026-11-06" in rendered
        assert row["title"] in rendered and row["link"] in rendered
        assert "기사 주장" in rendered


@pytest.mark.parametrize("published", ["2026-11-06T11:00:01+09:00", "2026-11-07T00:00:00+09:00", "invalid"])
def test_future_and_invalid_followups_never_refresh_or_render(published):
    pipeline = build_earnings_pipeline(current_context(), news=[followup(published_at=published)], now=NOW)
    packet, = pipeline["packets"]
    assert packet["latest_evidence_at"] == "2026-10-28"
    assert packet["articles"] == [] and pipeline["highlights"] == []
    assert "Alphabet Q3 2026 earnings disappoint" not in compact(pipeline)


def test_refresh_time_is_not_new_evidence_and_latest_article_wins_regardless_of_order():
    baseline = build_earnings_pipeline(current_context(), now=NOW)
    assert baseline["highlights"] == []
    assert baseline["packets"][0]["latest_evidence_at"] == "2026-10-28"
    earlier = followup(title="Alphabet Q3 2026 earnings guidance update",
                       link="https://www.cnbc.com/earlier", published_at="2026-11-04T10:00:00-05:00")
    for rows in ([followup(), earlier], [earlier, followup()]):
        pipeline = build_earnings_pipeline(current_context(), news=rows, now=NOW)
        assert pipeline["highlights"][0]["latest_evidence_at"] == "2026-11-06T00:00:00+09:00"
        assert followup()["title"] in compact(pipeline)


def test_same_period_preview_cannot_refresh_a_past_official_result():
    row = followup(title="Alphabet will report Q3 2026 earnings")
    pipeline = build_earnings_pipeline(current_context(), news=[row], now=NOW)
    official = next(p for p in pipeline["packets"] if p["official"])
    assert official["latest_evidence_at"] == "2026-10-28"
    assert official["articles"] == [] and pipeline["highlights"] == []
    assert row["title"] not in compact(pipeline)


def test_unknown_period_followup_cannot_refresh_or_borrow_official_metrics():
    pipeline = build_earnings_pipeline(current_context(), news=[followup(title="Alphabet earnings guidance update")], now=NOW)
    official = next(p for p in pipeline["packets"] if p["official"])
    discovered = next(p for p in pipeline["packets"] if not p["official"])
    assert official["latest_evidence_at"] == "2026-10-28"
    assert discovered["metrics"] == {} and discovered["fiscal_period"] == ""
    assert pipeline["highlights"] == [discovered]


def test_guidance_is_visible_alongside_fcf_and_capex_without_changing_evidence():
    data = current_context()
    guidance = "Next quarter revenue $20 to $30 billion; not current revenue"
    data["earnings_results"][0]["metrics"]["guidance"] = dict(status="available", text=guidance, source_url=SOURCE)
    pipeline = build_earnings_pipeline(data, news=[followup()], now=NOW)
    before = deepcopy(pipeline)
    for rendered in ("\n".join(report_earnings.earnings_story_lines(pipeline)), compact(pipeline)):
        assert "FCF: USD -10" in rendered and "CAPEX: USD 50" in rendered
        assert guidance.replace("$", r"\$") in rendered
        assert "전망 대상 기간은 원문 기준" in rendered
        assert "실제치 아님" in rendered and SOURCE in rendered
    assert pipeline == before


def test_compact_uses_packets_per_market_not_three_global_highlights():
    titles = ["JPMorgan Q3 2026 earnings beat estimates", "Eli Lilly Q3 2026 earnings miss estimates",
              "Walmart Q3 2026 earnings beat estimates", "Caterpillar Q3 2026 earnings beat estimates",
              "Costco quarterly results top estimates"]
    rows = [followup(title=title, link=f"https://www.cnbc.com/company-{i}") for i, title in enumerate(titles)]
    rows += [followup(title="기아는 3분기 실적 발표", market="KR", link="https://www.cnbc.com/kia")]
    pipeline = build_earnings_pipeline({}, [{"ticker": "CAT", "보유수량": 1}], news=rows, now=NOW)
    assert len(pipeline["highlights"]) == 3
    before = deepcopy(pipeline)
    us, kr = compact(pipeline), compact(pipeline, "KR")
    assert len([line for line in us.splitlines() if line.startswith("**") and " | " in line]) == 4
    assert "CAT" in us and "000270.KS" not in us
    assert "000270.KS" in kr and not any(t in kr for t in ("JPM", "LLY", "WMT", "CAT", "COST"))
    assert "기업·날짜 | 확인 구분 | 사실·출처 | 왜 중요한가 | 다음 확인" in us
    assert "기사 주장" in us and "공식 대조" in us
    assert compact(pipeline, "OTHER") == ""
    assert pipeline == before


def test_compact_one_issuer_once_preserves_news_claim_and_does_not_pad_empty_market():
    rows = [followup(), followup(title="Alphabet earnings guidance update", link="https://www.cnbc.com/unknown-period")]
    pipeline = build_earnings_pipeline(current_context(), news=rows, now=NOW)
    rendered = compact(pipeline)
    assert rendered.count("(GOOGL)") == 1
    assert "공식 발표 확인" in rendered and "기사 주장" in rendered
    assert compact(pipeline, "KR") == ""
    assert compact(build_earnings_pipeline({}, now=NOW)) == ""


def test_compact_official_future_call_is_schedule_not_a_result():
    scheduled = event(ticker="NVDA", event="NVIDIA earnings call", fiscal_period="FY2027Q3", date="2026-11-17",
                      event_kind="conference_call", event_status="scheduled", status="scheduled",
                      source_url="https://investor.nvidia.com/fixture", conference_call_at=None)
    pipeline = build_earnings_pipeline({"calendar_events": [scheduled]}, now=NOW)
    rendered = compact(pipeline)
    assert "2026-11-17" in rendered and "공식 일정·결과 미확인" in rendered
    assert "콜" in rendered and "결과 공개" in rendered
    assert "공식 발표 확인" not in rendered and "FCF:" not in rendered
    assert pipeline["highlights"] == []


def test_stale_result_remains_explicit_and_no_source_is_not_promoted():
    data = current_context()
    data["earnings_results"][0]["stale"] = True
    pipeline = build_earnings_pipeline(data, news=[followup()], now=NOW)
    assert "원문 재조회 실패·마지막 확인값" in compact(pipeline)
    packet = pipeline["packets"][0]
    packet.update(source_url="javascript:bad", metrics={}, articles=[])
    assert compact(pipeline) == ""


@pytest.mark.parametrize("changes", [
    {"publisher": "anonymous promotion", "link": "https://unverified.invalid/earnings"},
    {"link": "javascript:alert(1)"},
])
def test_unverified_source_cannot_create_or_refresh_official_evidence(changes):
    row = followup(**changes)
    news_only = build_earnings_pipeline({}, news=[row], now=NOW)
    assert news_only["packets"] == [] and compact(news_only) == ""
    existing = build_earnings_pipeline(current_context(), news=[row], now=NOW)
    assert existing["highlights"] == []
    assert existing["packets"][0]["latest_evidence_at"] == "2026-10-28"
    assert existing["packets"][0]["articles"] == []
    assert row["link"] not in compact(existing)


def test_trusted_news_title_is_still_a_claim_and_api_returns_lines():
    row = followup(source_kind="official_page", title="Alphabet Q3 2026 earnings beat estimates")
    pipeline = build_earnings_pipeline({}, news=[row], now=NOW)
    packet, = pipeline["packets"]
    assert not packet["official"] and packet["metrics"] == {} and pipeline["events"] == []
    lines = report_earnings.compact_catalyst_lines(pipeline, "US")
    assert isinstance(lines, list) and all(isinstance(line, str) for line in lines)
    rendered = "\n".join(lines)
    assert "기사 주장·공식 대조 대기" in rendered and "공식 발표 확인" not in rendered
    assert "공식 대조 대기" in rendered and row["link"] in rendered
    assert report_earnings.compact_catalyst_lines(pipeline, "KR") == []


def reading_cells(pipeline):
    row, = [line for line in report_earnings.compact_catalyst_lines(pipeline, "US")
            if line.startswith("**") and " | " in line]
    return row.split(" | ")


@pytest.mark.parametrize("keys,why_terms,check_terms", [
    (("guidance",), ("향후 수요", "이익률"), ("전망 대상 기간", "매출")),
    (("revenue",), ("판매량", "수요"), ("이익", "판매량", "가격", "환율")),
    (("profit",), ("이익률", "수익성"), ("매출", "일회성")),
    (("capex", "free_cash_flow"), ("투자", "현금", "자금 부담"), ("동일 기간", "투자 회수")),
    (("capex",), ("투자", "자금 부담"), ("FCF", "영업현금흐름")),
    (("free_cash_flow",), ("현금", "차입"), ("CAPEX", "운전자본")),
])
def test_compact_economic_reading_and_next_check_follow_supported_metrics(keys, why_terms, check_terms):
    data = current_context()
    data["earnings_results"][0]["metrics"] = {
        key: dict(status="available", text=f"Synthetic {key} evidence", source_url=SOURCE) for key in keys}
    pipeline = build_earnings_pipeline(data, now=NOW)
    before = deepcopy(pipeline)
    cells = reading_cells(pipeline)
    assert cells[3].startswith("해석(추정):")
    assert all(term in cells[3] for term in why_terms)
    assert all(term in cells[4] for term in check_terms)
    assert "컨센서스" not in cells[4] and "상회/하회 판단 보류" not in cells[4]
    assert "공식 발표 여부와 실제 수치" not in cells[3]
    assert pipeline == before


def test_guidance_and_cash_implications_coexist_and_deferred_guidance_is_next_check():
    data = current_context()
    data["earnings_results"][0]["metrics"]["guidance"] = dict(
        status="available", text="Next year revenue guidance is lower", source_url=SOURCE)
    cells = reading_cells(build_earnings_pipeline(data, now=NOW))
    assert "향후 수요" in cells[3] and "자금 부담" in cells[3]
    assert "전망 대상 기간" in cells[4] and "투자 회수" in cells[4]
    assert "수요 증가가 확인" not in cells[3] and "주가 상승" not in cells[3]
    deferred = reading_cells(build_earnings_pipeline(current_context(), now=NOW))
    assert deferred[4].startswith("컨퍼런스콜") and "회사 전망" in deferred[4]


def test_news_topic_is_conditional_not_official_and_hidden_older_topic_cannot_drive_reading():
    latest = followup(title="Alphabet earnings guidance update")
    older = followup(title="Alphabet earnings capital expenditure update", link="https://www.cnbc.com/older-topic",
                     published_at="2026-11-05T09:00:00-05:00")
    pipeline = build_earnings_pipeline({}, news=[older, latest], now=NOW)
    cells = reading_cells(pipeline)
    assert "기사 주장" in cells[1] and "향후 수요" in cells[3]
    assert "자금 부담" not in cells[3] and "설비투자" not in cells[3]
    assert "회사 전망 원문" in cells[4]
    assert "공식 발표 확인" not in " | ".join(cells)


def test_missing_or_unlinked_metrics_cannot_support_economic_reading_and_no_generic_footer():
    data = current_context()
    data["earnings_results"][0]["metrics"] = {
        "guidance": dict(status="missing", text="Guidance is higher", source_url=SOURCE),
        "capex": dict(status="available", text="CAPEX doubled", source_url=""),
    }
    pipeline = build_earnings_pipeline(data, now=NOW)
    cells = reading_cells(pipeline)
    assert "해석은 보류" in cells[3] and "자금 부담" not in cells[3]
    assert "매출" in cells[4] and "이익" in cells[4]
    assert "기존 수집 근거에서 기업 중복을 줄인" not in compact(pipeline)
    assert "미연결은 0·미발표·실적 부진이 아닙니다" in "\n".join(report_earnings.earnings_coverage_lines(pipeline))


def test_recent_unheld_catalyst_precedes_four_old_held_official_results():
    pipeline = build_earnings_pipeline(current_context(), now=NOW)
    seed = pipeline["packets"][0]
    old_packets = []
    for index in range(4):
        packet = deepcopy(seed)
        packet.update(ticker=f"HELD{index}", name=f"Synthetic held issuer {index}", relationship="보유")
        packet["event"]["ticker"] = packet["ticker"]
        old_packets.append(packet)
    pipeline["packets"] = old_packets
    assert all(f"(HELD{index})" in compact(pipeline) for index in range(4))

    recent = deepcopy(seed)
    recent.update(ticker="AMAT", name="Synthetic AMAT", relationship="시장 대표",
                  date="2026-11-06", latest_evidence_at="2026-11-06")
    recent["event"].update(ticker="AMAT", date="2026-11-06", release_at="2026-11-06")
    pipeline["packets"] = [*old_packets, recent]
    before = deepcopy(pipeline)
    rows = [line for line in report_earnings.compact_catalyst_lines(pipeline, "US")
            if line.startswith("**") and " | " in line]
    assert len(rows) == 4 and "(AMAT)" in rows[0]
    assert sum("(HELD" in row for row in rows) == 3
    assert pipeline == before
