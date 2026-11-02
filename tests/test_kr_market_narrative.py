"""Offline regression coverage for the bounded KR market synthesis bridge."""

from copy import deepcopy
from datetime import datetime, timedelta
import socket

import pytest

from stock_lab_core.public_market_data import parse_indicators, validated_investor_flows
from stock_lab_core.report_market_summary import market_summary, korean_sector_reading, korean_investor_reading, korean_flow_tables
from stock_lab_core.report_session import market_session_states


NOW = datetime.fromisoformat("2026-10-21T16:20:00+09:00")
DAY = NOW.date().isoformat()


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Narrative must not fetch data")
    monkeypatch.setattr(socket.socket, "connect", forbidden)


def payload():
    return {"domesticIndex": {market: {
        "itemCode": market,
        "meta": {"marketCode": market, "exchangeCode": "KRX", "currencyCode": "KRW"},
        "investorTrendBaseDate": DAY, "investorTrendExchangeType": "KRX",
        "investorTrends": [{"investorType": "foreigner", "netBuyAmount": "-12500000000"},
                           {"investorType": "organization", "netBuyAmount": "25000000000"}],
    } for market in ("KOSPI", "KOSDAQ")}}


def sector(ticker, name, value, **extra):
    return {"Ticker": ticker, "섹터": name, "구분": "한국 섹터", "기준일": DAY,
            "1일수익률": value, "수치종류": "확정 종가", **extra}


@pytest.fixture
def context():
    return {"sessions": {"KR": DAY, "US": "2026-10-20"},
            "prices": {"^KS11": {"date": DAY, "return": .012}},
            "closed_flow_rows": [sector("494670.KS", "조선", .047),
                                 sector("396500.KS", "한국 반도체", .021),
                                 sector("305540.KS", "2차전지", -.01)],
            "public_market_evidence": parse_indicators(payload(), NOW.date(), NOW),
            "market_evidence_checked_at": NOW.isoformat()}


def summarize(context, news=(), now=NOW):
    return market_summary(context, news, [], market_session_states(now, context["sessions"]), now)


def article(title, **extra):
    return {"title": title, "market": "KR", "session_date": DAY, "news_bucket": "session_news",
            "published_at": "2026-10-21T16:05:00+09:00", "publisher": "한국경제",
            "link": "https://www.hankyung.com/article/kr-narrative-fixture", **extra}


def test_observed_leader_and_investors_reach_all_summary_surfaces_without_news(context):
    original = deepcopy(context)
    result = summarize(context)
    for output in (result["headline"], result["overview"]):
        assert "관측 업종 ETF 3개" in output and "조선" in output and "+4.70%" in output
        assert "기관 순매수·외국인 순매도로 엇갈림" in output
        assert all(token not in output for token in ("억원", "조회 ", "프로그램", "매수 동기", "NXT", "저가", "저평가"))
    for output in (str(result["evidence"]) + korean_investor_reading(context, {"date": DAY}),):
        assert "조선(494670.KS) +4.70%" in output
        assert "3개 관측 표본 내 당일 수익률 최상위" in output
        assert "외국인 순매수 -125.00억원·기관 순매수 +250.00억원" in output
        assert DAY in output and "잠정·정정 가능" in output
        assert "프로그램은 투자자 구분이 아닌 거래 방식" in output
        assert "매수 동기는 확인되지 않습니다" in output
        assert "공개 수급 출처" in output and "조회 " + NOW.isoformat() in output
        assert "시장 전체 업종 순위·지수 상승 기여도·순매수액은 아닙니다" in output
        assert "저가매수" not in output and "저평가" not in output
    assert not result["market_claims"]["KR"]
    assert context == original


def test_daily_sector_leader_is_not_the_three_month_leader(context):
    context["closed_flow_rows"][0]["3개월수익률"] = -.2
    context["closed_flow_rows"][1]["3개월수익률"] = .8
    assert "최상위: 조선(494670.KS)" in str(summarize(context)["evidence"])


@pytest.mark.parametrize("defect", ["date", "stale", "mock", "missing", "nan", "us", "holding", "live_type"])
def test_invalid_sector_cannot_be_the_current_leader(context, defect):
    row = context["closed_flow_rows"][0]
    if defect == "date": row["기준일"] = "2026-10-20"
    elif defect == "stale": row["stale"] = True
    elif defect == "mock": row["is_mock"] = True
    elif defect == "missing": row.pop("1일수익률")
    elif defect == "nan": row["1일수익률"] = float("nan")
    elif defect == "us": row["Ticker"] = "XLI"
    elif defect == "holding": row["구분"] = "한국 개별주"
    elif defect == "live_type": row["수치종류"] = "장중"
    output = str(summarize(context)["evidence"])
    assert "조선(494670.KS)" not in output
    assert "최상위: 한국 반도체" in output


def test_duplicate_single_and_negative_samples_do_not_overstate_rank(context):
    row = sector("494670.KS", "조선", -.01)
    context["closed_flow_rows"] = [row]
    context["sector_rows"] = [deepcopy(row)]
    output = str(summarize(context)["evidence"])
    assert "ETF 1개 관측 표본: 조선" in output
    assert "최상위" not in output and "조선주 강세" not in output
    context["sector_rows"].append(sector("396500.KS", "한국 반도체", -.01))
    assert "공동 상위" in str(summarize(context)["evidence"])


def test_intraday_cannot_reuse_closed_sector_values(context):
    now = NOW.replace(hour=10)
    context["sessions"]["KR"] = "2026-10-20"
    context["intraday_prices"] = {"^KS11": {"date": DAY, "return": .01, "as_of": now.isoformat()}}
    output = summarize(context, now=now)["overview"]
    assert "조선" not in output
    context["intraday_prices"]["494670.KS"] = {"date": DAY, "return": .031, "as_of": now.isoformat()}
    output = summarize(context, now=now)["overview"]
    assert "조선" in output and "+3.10%" in output and "장중·미확정" in output
    assert "+4.70%" not in output


@pytest.mark.parametrize("defect", ["date", "fetched", "future_fetch", "mock", "unit", "scope", "exchange", "source", "missing"])
def test_invalid_public_flow_is_omitted_independently(context, defect):
    flows = context["public_market_evidence"]["flows"]
    obs = flows["KOSPI"]["institution"]
    fields = {"date": ("asof", "2026-10-20"), "fetched": ("fetched_at", (NOW - timedelta(minutes=6)).isoformat()),
              "future_fetch": ("fetched_at", (NOW + timedelta(seconds=1)).isoformat()),
              "mock": ("is_mock", True), "unit": ("unit", "KRW"), "scope": ("market", "KOSDAQ"),
              "exchange": ("exchange", "NXT"), "source": ("source", "unverified"), "missing": ("value", None)}
    field, value = fields[defect]
    obs[field] = value
    rows = validated_investor_flows(context["public_market_evidence"], session_date=DAY, checked_at=NOW.isoformat())
    assert not any(r["market"] == "KOSPI" and r["identity"] == "institution" for r in rows)
    assert any(r["market"] == "KOSPI" and r["identity"] == "foreign" for r in rows)
    assert any(r["market"] == "KOSDAQ" and r["identity"] == "institution" for r in rows)


@pytest.mark.parametrize("value,valid", [("0", True), ("-7500000000", True), (None, False), (True, False), ("1e8", False)])
def test_individual_requires_explicit_valid_amount(context, value, valid):
    raw = payload()
    raw["domesticIndex"]["KOSPI"]["investorTrends"].append({"investorType": "individual", "netBuyAmount": value})
    before = deepcopy(raw)
    context["public_market_evidence"] = parse_indicators(raw, NOW.date(), NOW)
    obs = context["public_market_evidence"]["flows"]["KOSPI"]["individual"]
    assert obs["ok"] is valid
    output = korean_investor_reading(context, {"date": DAY})
    assert ("개인 순매수" in output) is valid
    if value == "0": assert "개인 순매수 +0.00억원" in output
    assert raw == before


def test_absent_duplicate_and_program_fields_never_imply_individuals(context):
    raw = payload()
    raw["domesticIndex"]["KOSPI"]["investorTrends"].append({"investorType": "program", "netBuyAmount": "50000000000"})
    context["public_market_evidence"] = parse_indicators(raw, NOW.date(), NOW)
    assert "individual" not in context["public_market_evidence"]["flows"]["KOSPI"]
    output = summarize(context)["overview"]
    assert "개인 순매수" not in output and "+500.00" not in output
    raw["domesticIndex"]["KOSPI"]["investorTrends"] += [{"investorType": "individual", "netBuyAmount": "0"}] * 2
    obs = parse_indicators(raw, NOW.date(), NOW)["flows"]["KOSPI"]["individual"]
    assert not obs["ok"] and obs["value"] is None


def test_positive_news_drivers_are_attributed_not_invented(context):
    news = article("코스피 상승…조선주 강세, 기관 2조 순매수")
    result = summarize(context, [news])
    assert "조선주 강세·기관 매수" in result["headline"]
    assert "기사 주장" in result["headline"] and news["link"] in result["headline"]
    assert "저가" not in result["headline"]


@pytest.mark.parametrize("title,expected,absent", [
    ("코스피 상승…외국인 매도, 기관 순매수", "기관 매수", "외국인 매수"),
    ("코스피 상승…외국인 매도 기관 순매수", "기관 매수", "외국인 매수"),
    ("코스피 상승…기관 매도, 외국인 순매수", "외국인 매수", "기관 매수"),
    ("코스피 상승…기관 프로그램 순매수", "", "기관 매수"),
    ("코스피 상승…기관 순매수 전환 실패", "", "기관 매수"),
])
def test_buy_driver_does_not_cross_identity_or_method(context, title, expected, absent):
    claims = " ".join(summarize(context, [article(title)])["market_claims"]["KR"])
    assert expected in claims and absent not in claims


@pytest.mark.parametrize("extra", [{"session_date": "2026-10-20"},
                                  {"published_at": "2026-10-20T16:05:00+09:00"},
                                  {"news_bucket": "next_session_news"}])
def test_wrong_session_headline_cannot_explain_current_sector_strength(context, extra):
    result = summarize(context, [article("코스피 상승…조선주 강세, 기관 순매수", **extra)])
    assert not result["market_claims"]["KR"]
    assert "조선" in result["headline"] and "+4.70%" in result["headline"]


def test_no_valid_kr_evidence_does_not_add_flow_or_sector_claim(context):
    context.pop("closed_flow_rows")
    context["market_evidence_checked_at"] = (NOW + timedelta(minutes=6)).isoformat()
    result = summarize(context)
    assert "한국 관측 업종" not in dict(result["evidence"])
    assert "한국 투자자별 수급" not in dict(result["evidence"])


def test_concise_flow_describes_identity_divergence_without_amounts_or_motives(context):
    raw = payload()
    for item in raw["domesticIndex"].values():
        item["investorTrends"].append({"investorType": "individual", "netBuyAmount": "-7500000000"})
    context["public_market_evidence"] = parse_indicators(raw, NOW.date(), NOW)
    fact = {"date": DAY, "live": False, "market": "KR"}
    short = korean_investor_reading(context, fact, concise=True)
    assert short == "잠정 수급은 KOSPI·KOSDAQ 모두 기관 순매수·외국인·개인 순매도로 엇갈림"
    sector_text = korean_sector_reading(context, fact, market_session_states(NOW, context["sessions"]), NOW, concise=True)
    assert len(sector_text + short) < 160
    for surface in (summarize(context)["headline"], summarize(context)["overview"]):
        assert short in surface
        assert all(term not in surface for term in ("억원", "조회", "프로그램", "저가", "매수 동기"))


def test_missing_identity_and_market_are_not_inferred_in_short_prose(context):
    flows = context["public_market_evidence"]["flows"]
    flows["KOSPI"]["foreign"]["value"] = None
    flows.pop("KOSDAQ")
    short = korean_investor_reading(context, {"date": DAY}, concise=True)
    assert short == "잠정 수급은 KOSPI 기관 순매수"
    flows["KOSPI"]["institution"]["value"] = 0
    assert korean_investor_reading(context, {"date": DAY}, concise=True) == "잠정 수급은 KOSPI 기관 순매수 0"


def leader_reading(context, news, now=NOW):
    fact = {"date": DAY, "live": now.hour < 15, "market": "KR"}
    return korean_sector_reading(context, fact, market_session_states(now, context["sessions"]), now, news, concise=True)


def test_leader_adds_at_most_one_actual_attributed_title_without_index_causality(context):
    older = article("한화오션 수주 확대에 조선주 강세", link="https://www.hankyung.com/older")
    newer = article("현대중공업 조선업 수주 증가", published_at="2026-10-21T16:10:00+09:00")
    before = deepcopy((context, older, newer))
    output = leader_reading(context, [older, newer])
    assert output.count("관련 보도") == 1
    assert newer["title"] in output and newer["link"] in output and newer["publisher"] in output
    assert older["title"] not in output and "기사 주장" in output
    assert "코스피" not in output and "때문" not in output
    assert (context, older, newer) == before


@pytest.mark.parametrize("extra", [
    {"market": "US"}, {"market": "GLOBAL"}, {"session_date": "2026-10-20"},
    {"published_at": "2026-10-20T16:00:00+09:00"}, {"published_at": (NOW + timedelta(seconds=1)).isoformat()},
    {"news_bucket": "next_session_news"}, {"news_bucket": "other_market_news"},
    {"link": "javascript:bad"}, {"publisher": "unknown", "link": "https://unknown.invalid/news"},
    {"title": "코스피 상승…조선주 하락"}, {"title": "반도체 강세에 코스피 상승"},
    {"title": "조선호텔 주가 상승"}, {"title": "[장전] 코스피 전망, 조선주 상승 예상"},
])
def test_leader_news_rejects_wrong_source_time_sector_direction_and_outlook(context, extra):
    assert "관련 보도" not in leader_reading(context, [dict(article("조선주 강세"), **extra)])


def test_negative_relative_leader_keeps_negative_source_title(context):
    context["closed_flow_rows"][0]["1일수익률"] = -.005
    context["closed_flow_rows"][1]["1일수익률"] = -.02
    negative = article("조선주 하락, 수주 부진")
    output = leader_reading(context, [negative, article("조선주 강세")])
    assert "-0.50%" in output and negative["title"] in output
    assert "조선주 강세" not in output


def test_leader_title_and_publication_exact_bounds(context):
    title = "조선주 강세 " + "가" * (140 - len("조선주 강세 "))
    assert "관련 보도" in leader_reading(context, [article(title, published_at=NOW.isoformat())])
    assert "관련 보도" not in leader_reading(context, [article(title + "가")])


def test_program_evidence_is_separate_and_never_enters_compact_narrative(context):
    raw = payload()
    raw["domesticIndex"]["KOSPI"]["programTrend"] = {
        "arbitrageNetBuyAmount": "-100000000", "nonArbitrageNetBuyAmount": "300000000", "totalNetBuyAmount": "200000000"}
    context["public_market_evidence"] = parse_indicators(raw, NOW.date(), NOW)
    result = summarize(context)
    evidence = dict(result["evidence"])
    assert "프로그램 순매수 표 참조" in evidence["한국 프로그램 매매"]
    program = "\n".join(korean_flow_tables(context, {"date": DAY}))
    assert "KOSPI | -1.00 | +3.00 | +2.00 | " + DAY in program
    assert "프로그램 자체 기준시각이 없어" in program and "같은 응답의 투자자 수급 기준일" in program
    assert DAY in program and NOW.isoformat() in program and "[Npay 증권 공개 데이터](https://" in program
    assert "투자자별 순매수와 합산하거나 기관 매수액으로 해석하지 않습니다" in program
    assert "미연결" not in program
    for surface in (result["overview"], result["headline"]):
        assert "프로그램" not in surface and "억원" not in surface
    raw["domesticIndex"]["KOSPI"]["programTrend"]["totalNetBuyAmount"] = "1"
    context["public_market_evidence"] = parse_indicators(raw, NOW.date(), NOW)
    evidence = dict(summarize(context)["evidence"])
    assert "한국 프로그램 매매" not in evidence
    assert "프로그램 자료 미연결" in "\n".join(korean_flow_tables(context, {"date": DAY}))


def test_flow_table_columns_zero_missing_provenance_and_no_duplicate_amount_dump(context):
    before = deepcopy(context)
    lines = korean_flow_tables(context, {"date": DAY})
    assert "시장 | 개인 | 외국인 | 기관 | 기준일" in lines
    assert "KOSPI | — | -125.00 | +250.00 | " + DAY in lines
    assert sum("[Npay 증권 공개 데이터]" in line for line in lines) == 1
    assert sum("조회 " in line for line in lines) == 1
    assert "시장 | 차익 | 비차익 | 합계 | 기준일" not in lines
    assert context == before
    context["public_market_evidence"]["flows"]["KOSPI"]["foreign"]["value"] = 0
    assert "KOSPI | — | +0.00 | +250.00 | " + DAY in korean_flow_tables(context, {"date": DAY})
    assert "억원" not in dict(summarize(context)["evidence"])["한국 투자자별 수급"]
    assert korean_flow_tables(context, {"date": "2026-10-20"}) == []


def test_program_table_can_render_without_investor_totals(context):
    raw = payload()
    raw["domesticIndex"]["KOSPI"]["programTrend"] = {
        "arbitrageNetBuyAmount": "0", "nonArbitrageNetBuyAmount": "0", "totalNetBuyAmount": "0"}
    context["public_market_evidence"] = parse_indicators(raw, NOW.date(), NOW)
    context["public_market_evidence"]["flows"] = {}
    lines = korean_flow_tables(context, {"date": DAY})
    assert "시장 | 차익 | 비차익 | 합계 | 기준일" in lines
    assert "시장 | 개인 | 외국인 | 기관 | 기준일" not in lines
    assert "KOSPI | +0.00 | +0.00 | +0.00 | " + DAY in lines
