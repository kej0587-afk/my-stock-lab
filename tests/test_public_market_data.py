"""Offline contracts; provider-shaped fixtures projected from 2026-11-02 GETs.

Live evidence: 2026-11-02 16:03:45-46 KST, all three endpoints HTTP 200.
Flow date 2026-11-02; KOSPI foreign -3743.25 / institution +12329.67;
KOSDAQ foreign -321.42 / institution +624.03 (100m KRW, provisional).
Turnover 148702.20 / 48000.34 (100m KRW). creditLoan 286840, 2026-10-29.
Legacy finance.naver.com/sise/sise_deal_trend_day.naver returned HTTP 404;
api.stock.naver.com/domestic/index/KOSPI/basic also returned HTTP 404.
No broker configuration or secrets were read for these public queries.
"""

from copy import deepcopy
from datetime import date, datetime, timedelta
import json
import socket

import pytest
import requests

from stock_lab_core import public_market_data as public
from stock_lab_core import market_sentiment as sentiment

NOW = datetime(2026, 11, 2, 16, 3, 46, tzinfo=public.KST)
AS_OF = date(2026, 11, 2)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Unexpected live network")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    public.load_public_market_evidence.clear()
    yield
    public.load_public_market_evidence.clear()


@pytest.fixture
def indicators():
    result = {"domesticIndex": {}}
    for market, foreign, institution, counts in (
        ("KOSPI", "-374325000000", "1232967000000", (4, 653, 29, 230, 0)),
        ("KOSDAQ", "-32142000000", "62403000000", (5, 1115, 71, 553, 0)),
    ):
        result["domesticIndex"][market] = {
            "itemCode": market,
            "meta": {"marketCode": market, "exchangeCode": "KRX", "currencyCode": "KRW"},
            "investorTrendBaseDate": "2026-11-02", "investorTrendExchangeType": "KRX",
            "investorTrends": [{"investorType": "foreigner", "netBuyAmount": foreign},
                               {"investorType": "organization", "netBuyAmount": institution}],
            "price": {"localTradedAt": "2026-11-02T16:03:00+09:00"},
            "breadth": {"exchangeType": "KRX", **dict(zip(
                ("upperLimitCount", "risingCount", "unchangedCount", "fallingCount", "lowerLimitCount"),
                map(str, counts)))},
        }
    return result


@pytest.fixture
def turnover():
    return {"datas": [
        {"itemCode": market, "stockExchangeType": {"code": code, "nationCode": "KOR"},
         "localTradedAt": "2026-11-02T16:03:00+09:00", "accumulatedTradingValueRaw": raw,
         "accumulatedTradingValue": formatted}
        for market, code, raw, formatted in (
            ("KOSPI", "KS", "14870220000000", "14,870,220백만"),
            ("KOSDAQ", "KQ", "4800034000000", "4,800,034백만"))]}


@pytest.fixture
def deposit():
    return {"content": [{"bizdate": "20261029", "creditLoan": "286840"},
                        {"bizdate": "20261028", "creditLoan": "289137"}]}


def test_four_actual_market_totals_and_independent_dates(indicators, turnover, deposit):
    data = public.parse_indicators(indicators, AS_OF, NOW)
    values = [obs["value"] for market in public.MARKETS for obs in data["flows"][market].values()]
    assert values == [-3743.25, 12329.67, -321.42, 624.03]
    assert data["flows"]["KOSPI"]["foreign"]["raw_unit"] == "KRW"
    assert data["flows"]["KOSPI"]["foreign"]["provisional"]
    assert data["breadth"]["KOSPI"]["counts"]["risingCount"] == 653
    assert data["breadth"]["KOSPI"]["date_basis"] == "index_quote_timestamp"
    assert "자체 기준시각 미제공" in data["breadth"]["KOSPI"]["limitation"]
    money = public.parse_turnover(turnover, AS_OF, NOW)
    assert money["KOSPI"]["value"] == 148702.20
    assert money["KOSDAQ"]["value"] == 48000.34
    margin = public.parse_margin_debt(deposit, AS_OF, NOW)
    assert margin["value"] == 286840 and margin["asof"] == "2026-10-29"
    assert margin["asof"] != money["KOSPI"]["asof"]


@pytest.mark.parametrize("value", [None, "", "-", "NaN", "Infinity", "1e8", True, 1.5, "12억원", "1,000"])
def test_invalid_net_values_are_not_zero_or_coerced(indicators, value):
    indicators["domesticIndex"]["KOSPI"]["investorTrends"][0]["netBuyAmount"] = value
    data = public.parse_indicators(indicators, AS_OF, NOW)
    assert not data["flows"]["KOSPI"]["foreign"]["ok"]
    assert data["flows"]["KOSPI"]["foreign"]["value"] is None
    assert data["flows"]["KOSPI"]["institution"]["ok"]
    assert data["flows"]["KOSDAQ"]["foreign"]["ok"]


def test_zero_missing_and_duplicate_investors_are_distinct(indicators):
    item = indicators["domesticIndex"]["KOSPI"]
    item["investorTrends"] = [{"investorType": "foreigner", "netBuyAmount": "0"}]
    parsed = public.parse_indicators(indicators, AS_OF, NOW)["flows"]["KOSPI"]
    assert parsed["foreign"]["value"] == 0 and parsed["foreign"]["ok"]
    assert not parsed["institution"]["ok"]
    item["investorTrends"] *= 2
    assert not public.parse_indicators(indicators, AS_OF, NOW)["flows"]["KOSPI"]["foreign"]["ok"]


@pytest.mark.parametrize("field,value,status", [
    ("investorTrendBaseDate", "2026-11-03", "future_data"),
    ("investorTrendBaseDate", "2026-10-25", "stale_data"),
    ("investorTrendBaseDate", "2026-02-30", "invalid_date"),
    ("investorTrendBaseDate", None, "invalid_date"),
    ("investorTrendExchangeType", "NXT", "invalid_scope"),
    ("itemCode", "KOSDAQ", "invalid_scope"),
])
def test_flow_dates_and_exchange_fail_closed(indicators, field, value, status):
    indicators["domesticIndex"]["KOSPI"][field] = value
    obs = public.parse_indicators(indicators, AS_OF, NOW)["flows"]["KOSPI"]["foreign"]
    assert not obs["ok"] and obs["status"] == status and obs["value"] is None


def test_currency_not_assumed_and_quote_date_does_not_replace_flow_date(indicators):
    item = indicators["domesticIndex"]["KOSPI"]
    item["meta"]["currencyCode"] = "USD"
    assert not public.parse_indicators(indicators, AS_OF, NOW)["flows"]["KOSPI"]["foreign"]["ok"]
    item["meta"]["currencyCode"] = "KRW"
    item["investorTrendBaseDate"] = "2026-10-30"
    assert public.parse_indicators(indicators, AS_OF, NOW)["flows"]["KOSPI"]["foreign"]["asof"] == "2026-10-30"


@pytest.mark.parametrize("at", [None, "2026-11-02", "2026-11-02T16:00:00", "2026-11-02T16:10:00+09:00"])
def test_breadth_and_turnover_require_aware_nonfuture_time(indicators, turnover, at):
    indicators["domesticIndex"]["KOSPI"]["price"]["localTradedAt"] = at
    turnover["datas"][0]["localTradedAt"] = at
    assert not public.parse_indicators(indicators, AS_OF, NOW)["breadth"]["KOSPI"]["ok"]
    assert not public.parse_turnover(turnover, AS_OF, NOW)["KOSPI"]["ok"]


@pytest.mark.parametrize("field,value", [("risingCount", "-1"), ("fallingCount", None), ("exchangeType", "NXT")])
def test_breadth_partial_or_invalid_is_missing(indicators, field, value):
    indicators["domesticIndex"]["KOSPI"]["breadth"][field] = value
    data = public.parse_indicators(indicators, AS_OF, NOW)
    assert not data["breadth"]["KOSPI"]["ok"]
    assert data["flows"]["KOSPI"]["foreign"]["ok"]


@pytest.mark.parametrize("formatted", ["14,870,220억원", "14,870,221백만", "14,870,220", "14,87,0220백만", None])
def test_turnover_checks_explicit_million_krw_against_raw(turnover, formatted):
    turnover["datas"][0]["accumulatedTradingValue"] = formatted
    assert public.parse_turnover(turnover, AS_OF, NOW)["KOSPI"]["status"] == "invalid_unit"


@pytest.mark.parametrize("payload", [None, [], {}, {"content": None}, {"content": [None]},
    {"content": [{"bizdate": "20261103", "creditLoan": "1"}]},
    {"content": [{"bizdate": "20261001", "creditLoan": "1"}]},
    {"content": [{"bizdate": "20261029", "creditLoan": "-1"}]}])
def test_margin_missing_future_stale_and_negative_never_reported(payload):
    obs = public.parse_margin_debt(payload, AS_OF, NOW)
    assert not obs["ok"] and obs["value"] is None and obs["reason"]


@pytest.mark.parametrize("payload", [None, [], {}, {"domesticIndex": []}, {"datas": [None]}])
def test_invalid_root_does_not_crash(payload):
    assert not public.parse_indicators(payload, AS_OF, NOW)["flows"]["KOSPI"]["foreign"]["ok"]
    assert not public.parse_turnover(payload, AS_OF, NOW)["KOSPI"]["ok"]


class Response:
    def __init__(self, payload=None, status=200, content_type="application/json"):
        self.status_code = status
        self.headers = {"Content-Type": content_type}
        self.text = json.dumps(payload)
        self.closed = False

    def close(self):
        self.closed = True


def collect(indicators, turnover, deposit):
    responses = [Response(payload) for payload in (indicators, turnover, deposit)]
    queue = iter(responses)
    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return next(queue)

    result = public.read_public_market_evidence(AS_OF.isoformat(), request=get, now=lambda: NOW)
    return result, calls, responses


def test_three_bounded_readonly_calls_close_responses_and_preserve_provenance(indicators, turnover, deposit):
    data, calls, responses = collect(indicators, turnover, deposit)
    assert data["ok"] and len(calls) == 3 and all(r.closed for r in responses)
    assert calls[0][0] == public.INDICATORS_URL
    assert calls[1][0] == public.TURNOVER_URL
    assert calls[2][0] == public.DEPOSIT_URL
    assert calls[2][1]["params"] == {"startIdx": 0, "pageSize": 3}
    for _, options in calls:
        assert options["timeout"] == (3, 6) and options["stream"] is True
        assert options["allow_redirects"] is False
        assert "Authorization" not in options["headers"]
    assert data["flows"]["KOSPI"]["foreign"]["http_status"] == 200


@pytest.mark.parametrize("failure,expected", [(requests.Timeout("PRIVATE_VALUE"), "timeout"),
    (requests.ConnectionError("PRIVATE_VALUE"), "network_error"),
    (Response(status=429), "http_error"), (Response(content_type="text/html"), "invalid_response")])
def test_transport_failure_sanitized_and_partial_success_kept(indicators, turnover, deposit, failure, expected, caplog):
    queue = iter([failure, Response(turnover), Response(deposit)])

    def get(*args, **kwargs):
        result = next(queue)
        if isinstance(result, Exception):
            raise result
        return result

    data = public.read_public_market_evidence("2026-11-02", request=get, now=lambda: NOW)
    assert not data["ok"]
    assert data["flows"]["KOSPI"]["foreign"]["status"] == expected
    assert data["turnover"]["KOSPI"]["ok"] and data["margin_debt"]["ok"]
    assert "PRIVATE_VALUE" not in json.dumps(data) + caplog.text
    if isinstance(failure, Response):
        assert failure.closed


def test_clean_transport_does_not_use_netrc_or_environment_auth(monkeypatch, indicators, turnover, deposit):
    queue = iter([Response(indicators), Response(turnover), Response(deposit)])

    def get(session, *args, **kwargs):
        assert session.trust_env is False
        assert session.auth is None and not session.cookies
        return next(queue)

    monkeypatch.setattr(requests.Session, "get", get)
    assert public.read_public_market_evidence("2026-11-02", now=lambda: NOW)["ok"]


def test_cache_reuses_detached_result_and_clear(monkeypatch, indicators, turnover, deposit):
    data, _, _ = collect(indicators, turnover, deposit)
    calls = []

    def read(day):
        calls.append(day)
        return deepcopy(data)

    monkeypatch.setattr(public, "read_public_market_evidence", read)
    first = public.load_public_market_evidence("2026-11-02")
    first["flows"]["KOSPI"]["foreign"]["value"] = 7
    assert public.load_public_market_evidence("2026-11-02")["flows"]["KOSPI"]["foreign"]["value"] == -3743.25
    assert len(calls) == 1
    public.load_public_market_evidence.clear()
    public.load_public_market_evidence("2026-11-02")
    assert len(calls) == 2


def test_render_has_four_public_flows_without_changing_mock_broker(indicators, turnover, deposit):
    data, _, _ = collect(indicators, turnover, deposit)

    class MockClient:
        connection_info = {"status": "ready", "environment": "mock"}
        def get_market_snapshot(self, kind):
            pytest.fail("Must not query mock broker")

    broker = sentiment.load_investor_flow_evidence(MockClient())
    context = {"public_market_evidence": data, "market_observation_evidence": broker,
               "market_evidence_checked_at": NOW.isoformat(), "quote_checked_at": "2026-10-30T16:00:00+09:00"}
    before = deepcopy(context)
    rows = sentiment.sentiment_evidence(context)["rows"]
    flows = [row for row in rows if "순매수" in row["지표"]]
    assert len(flows) == 4 and all(row["관측"] != "미연결" for row in flows)
    assert all("별도 공개 출처" in row["범위·한계"] and row["출처"] == public.FLOW_SOURCE for row in flows)
    assert all(obs["status"] == "mock_excluded" for obs in broker.values())
    assert context == before
    assert next(r for r in rows if r["지표"] == "신용융자잔고")["기준일"] == "2026-10-29"
    assert next(r for r in rows if r["지표"] == "신고가/신저가")["관측"] == "미연결"


@pytest.mark.parametrize("offset", [-1, 301])
def test_future_or_old_collection_is_not_rendered(indicators, turnover, deposit, offset):
    data, _, _ = collect(indicators, turnover, deposit)
    rows = sentiment.sentiment_evidence({"public_market_evidence": data,
        "market_evidence_checked_at": (NOW + timedelta(seconds=offset)).isoformat()})["rows"]
    assert all(row["관측"] == "미연결" for row in rows if "순매수" in row["지표"])


def test_invalid_request_date_does_not_start_network():
    with pytest.raises(ValueError, match="ISO date"):
        public.read_public_market_evidence("bad-date")


def program_payload(arb="-18655058551", nonarb="95449946652", total="76794888101"):
    return dict(arbitrageNetBuyAmount=arb, nonArbitrageNetBuyAmount=nonarb, totalNetBuyAmount=total)


def test_optional_program_uses_same_get_and_keeps_required_success(indicators, turnover, deposit):
    baseline, _, _ = collect(indicators, turnover, deposit)
    assert "programs" not in baseline
    indicators["domesticIndex"]["KOSPI"]["programTrend"] = program_payload()
    indicators["domesticIndex"]["KOSDAQ"]["programTrend"] = program_payload("1699032960", "-43333917180", "-41634884220")
    before = deepcopy(indicators)
    data, calls, responses = collect(indicators, turnover, deposit)
    rows = public.validated_program_flows(data, session_date=AS_OF.isoformat(), checked_at=NOW.isoformat())
    assert data["ok"] and len(calls) == 3 and all(r.closed for r in responses)
    assert data["flows"] == baseline["flows"] and indicators == before
    assert [r["value"] for r in rows] == [767.94888101, -416.34884220]
    assert rows[0]["arbitrage"] == -186.55058551 and rows[0]["non_arbitrage"] == 954.49946652
    assert rows[0]["raw_value"] == rows[0]["raw_arbitrage"] + rows[0]["raw_non_arbitrage"]
    assert rows[0]["http_status"] == 200 and rows[0]["source_url"] == public.FLOW_SOURCE
    assert rows[0]["date_basis"] == "investorTrendBaseDate"
    assert "프로그램 자체 기준시각 미제공" in rows[0]["limitation"]


@pytest.mark.parametrize("field", ["arbitrageNetBuyAmount", "nonArbitrageNetBuyAmount", "totalNetBuyAmount"])
@pytest.mark.parametrize("value", [None, True, 1.5, "1e8", "1,000", "", "NaN"])
def test_invalid_optional_program_does_not_poison_investors(indicators, turnover, deposit, field, value):
    indicators["domesticIndex"]["KOSPI"]["programTrend"] = dict(program_payload(), **{field: value})
    data, calls, _ = collect(indicators, turnover, deposit)
    assert data["ok"] and len(calls) == 3
    assert data["flows"]["KOSPI"]["institution"]["ok"]
    assert not data["programs"]["KOSPI"]["ok"]
    assert public.validated_program_flows(data, session_date=AS_OF.isoformat(), checked_at=NOW.isoformat()) == []


def test_program_total_must_match_exact_integer_sum_and_zero_is_valid(indicators, turnover, deposit):
    indicators["domesticIndex"]["KOSPI"]["programTrend"] = program_payload(total="76794888102")
    data, _, _ = collect(indicators, turnover, deposit)
    assert data["ok"] and not data["programs"]["KOSPI"]["ok"]
    indicators["domesticIndex"]["KOSPI"]["programTrend"] = program_payload("0", "0", "0")
    data, _, _ = collect(indicators, turnover, deposit)
    assert data["programs"]["KOSPI"]["value"] == 0
    assert len(public.validated_program_flows(data, session_date=AS_OF.isoformat(), checked_at=NOW.isoformat())) == 1


@pytest.mark.parametrize("field,value", [("investorTrendBaseDate", "2026-11-03"),
    ("investorTrendBaseDate", "2026-10-20"), ("investorTrendBaseDate", None),
    ("investorTrendExchangeType", "NXT"), ("itemCode", "KOSDAQ")])
def test_program_parser_validates_shared_date_and_scope(indicators, field, value):
    item = indicators["domesticIndex"]["KOSPI"]
    item["programTrend"] = program_payload()
    item[field] = value
    data = public.parse_indicators(indicators, AS_OF, NOW)
    assert not data["programs"]["KOSPI"]["ok"]


@pytest.mark.parametrize("field,value", [("unit", "KRW"), ("raw_unit", "USD"), ("market", "KOSDAQ"),
    ("exchange", "NXT"), ("date_basis", "guessed"), ("source", "unknown"), ("is_mock", True),
    ("raw_value", 76794888102), ("arbitrage", -1), ("source_url", "javascript:bad"), ("asof", "2026-10-30")])
def test_program_consumer_rechecks_saved_scope_units_and_values(indicators, field, value):
    indicators["domesticIndex"]["KOSPI"]["programTrend"] = program_payload()
    data = public.parse_indicators(indicators, AS_OF, NOW)
    data["programs"]["KOSPI"][field] = value
    assert not public.validated_program_flows(data, session_date=AS_OF.isoformat(), checked_at=NOW.isoformat())


@pytest.mark.parametrize("seconds,valid", [(-1, False), (0, True), (300, True), (301, False)])
def test_program_freshness_exact_bounds(indicators, seconds, valid):
    indicators["domesticIndex"]["KOSPI"]["programTrend"] = program_payload()
    data = public.parse_indicators(indicators, AS_OF, NOW)
    rows = public.validated_program_flows(data, session_date=AS_OF.isoformat(),
        checked_at=(NOW + timedelta(seconds=seconds)).isoformat())
    assert bool(rows) is valid
