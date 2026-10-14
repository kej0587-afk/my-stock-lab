from datetime import datetime, timezone

import pytest
import requests

from stock_lab_core.kiwoom_data import KiwoomConfig, KiwoomDataClient
from stock_lab_core.kiwoom_market import MARKET_REQUESTS, normalize_market_rows, market_evidence_summary
from stock_lab_core.news_evidence import build_price_news_evidence, KST


class Response:
    status_code = 200

    def __init__(self, payload, more="N"):
        self.payload = payload
        self.headers = {"cont-yn": more}

    def json(self):
        return self.payload

    def close(self):
        pass


class Session:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def client_with(responses):
    session = Session([Response({"return_code": 0, "token": "TEST_TOKEN", "token_type": "bearer",
                                 "expires_dt": "20261014090000"}), *responses])
    client = KiwoomDataClient(KiwoomConfig(enabled=True, appkey="TEST", secretkey="TEST"), session=session,
                              now=lambda: datetime(2026, 10, 13, tzinfo=timezone.utc).timestamp())
    return client, session


def test_turnover_units_and_missing_values():
    item = {"stk_cd": "005930", "stk_nm": "삼성전자", "cur_prc": "-65,000", "flu_rt": "-2.1",
            "trde_prica": "1,235", "now_trde_qty": "16,594", "now_rank": "1"}
    result = normalize_market_rows({"trde_prica_upper": [item, item]}, "turnover")
    assert len(result["rows"]) == 1
    row = result["rows"][0]
    assert row["현재가(원)"] == 65000
    assert row["거래대금(백만원)"] == 1235
    assert row["거래량(주)"] == 16594
    assert row["등락률(%)"] == -2.1
    assert row["전일순위"] is None
    assert "순매수가 아닙니다" in market_evidence_summary(result, {})[0]


@pytest.mark.parametrize("total,up,down,expected", [(10, 6, 4, 60), (10, 0, 0, 0), (10, 11, 0, None),
    (10, 6, 5, None), (0, 0, 0, None), (None, 6, 0, None), (10, "", 2, None), (10, 6.5, 0, None)])
def test_breadth_missing_and_inconsistent_counts(total, up, down, expected):
    result = normalize_market_rows({"thema_grp": [{"thema_grp_cd": "100", "thema_nm": "반도체",
        "flu_rt": "+2", "stk_num": total, "rising_stk_num": up, "fall_stk_num": down}]}, "themes")
    row = result["rows"][0]
    assert row["상승비율(%)"] == expected
    assert (row["구분"] == "당일 상승 확산") == (expected == 60)


def test_sector_flow_signed_units_not_derived_from_volume():
    result = normalize_market_rows({"inds_netprps": [{"inds_cd": "001", "inds_nm": "코스피",
        "frgnr_netprps": "-120", "orgn_netprps": "20.5", "ind_netprps": "", "flu_rt": None}]}, "sector_kospi")
    row = result["rows"][0]
    assert row["외국인 순매수(억원)"] == -120
    assert row["기관 순매수(억원)"] == 20.5
    assert row["개인 순매수(억원)"] is None
    assert row["등락률(%)"] is None


@pytest.mark.parametrize("kind,body", [
    ("turnover", {"mrkt_tp": "000", "mang_stk_incls": "0", "stex_tp": "1"}),
    ("themes", {"qry_tp": "0", "date_tp": "10", "flu_pl_amt_tp": "3", "stex_tp": "1"}),
    ("theme_members", {"date_tp": "10", "stex_tp": "1", "thema_grp_cd": "100"}),
    ("sector_kospi", {"mrkt_tp": "0", "amt_qty_tp": "0", "stex_tp": "1"}),
    ("sector_kosdaq", {"mrkt_tp": "1", "amt_qty_tp": "0", "stex_tp": "1"}),
])
def test_official_requests_are_bounded_read_only(kind, body):
    client, session = client_with([Response({"return_code": 0}, more="Y"), Response({"return_code": 0})])
    result = client.get_market_snapshot(kind, "100")
    client.get_market_snapshot(kind, "100")
    assert len(session.calls) == 3  # one token, two reads; no retries/pagination
    assert session.calls[1][1]["json"] == body
    assert session.calls[1][1]["headers"]["api-id"] == MARKET_REQUESTS[kind][1]
    assert result["has_more"] is True
    assert result["asof"] == ""
    assert result["fetched_at"]
    assert result["status"] == "invalid_response"


def test_disabled_unknown_and_bad_theme_do_not_connect():
    session = Session([])
    disabled = KiwoomDataClient(session=session)
    assert disabled.get_market_snapshot("turnover")["status"] == "disabled"
    client = KiwoomDataClient(KiwoomConfig(enabled=True, appkey="T", secretkey="T"), session=session)
    for kind, theme in [("orders", ""), ("theme_members", ""), ("theme_members", "../100")]:
        assert not client.get_market_snapshot(kind, theme)["ok"]
    assert not session.calls


def test_timeout_is_sanitized_and_next_source_can_succeed():
    client, session = client_with([requests.Timeout("SECRET"), Response({"return_code": 0, "thema_grp": []})])
    failed = client.get_market_snapshot("turnover")
    assert failed["status"] == "timeout"
    assert "SECRET" not in str(failed)
    assert client.get_market_snapshot("themes")["status"] == "no_data"
    assert len(session.calls) == 3


def test_news_is_dated_evidence_not_causal_assertion():
    def item(published, category="종목 직접", link="https://example.com/report"):
        return {"title": published, "published": published, "category": category, "link": link, "reason": "실적 관련 보도"}
    items = [item("2026-10-13 09:00"), item("2026-10-14 09:00"), item("2026-10-01 09:00"),
             item(""), item("2026-10-13 08:00", "섹터/테마"), item("2026-10-13 07:00", link="javascript:alert(1)")]
    evidence = build_price_news_evidence(items, -1.2, now=datetime(2026, 10, 13, 10, tzinfo=KST))
    assert len(evidence["rows"]) == 1
    assert "-1.20%" in evidence["observation"]
    assert "인과관계는 미확인" in evidence["conclusion"]
    assert "원인을 확정하지" in build_price_news_evidence([], float("nan"))["conclusion"]


def test_korean_news_search_does_not_need_yahoo_when_name_known(monkeypatch):
    from stock_lab_core import news

    monkeypatch.setattr(news, "get_yfinance_company_names", lambda _: pytest.fail("unnecessary Yahoo call"))
    queries, names = news.build_stock_news_queries("098120", "마이크로컨텍솔")
    assert names == ["마이크로컨텍솔"]
    assert "최신 뉴스" in queries[0]
    assert [item["label"] for item in news.google_news_locales_for_ticker("098120")] == ["KR"]


def test_future_news_not_treated_as_recent():
    from datetime import timedelta
    from stock_lab_core.news import is_news_within_days

    now = datetime.now(timezone.utc)
    assert is_news_within_days(now - timedelta(hours=1), 2)
    assert not is_news_within_days(now + timedelta(days=1), 2)
    assert not is_news_within_days(datetime(2026, 10, 13), 2)
    assert not is_news_within_days("2026-10-13", 2)


def test_ticker_display_name_still_resolves_company(monkeypatch):
    from stock_lab_core import news

    monkeypatch.setattr(news, "get_yfinance_company_names", lambda _: ["Samsung Electronics"])
    assert news.get_news_company_names("005930.KS", "005930.KS") == ["Samsung Electronics"]


def test_mock_market_reads_remain_visible_with_environment(app_module, monkeypatch):
    class Client:
        def get_market_snapshot(self, *args):
            return {"ok": True, "is_mock": True, "rows": [{"종목명": "FAKE"}]}

    app_module.fetch_kiwoom_market_snapshot.clear()
    monkeypatch.setattr(app_module, "get_kiwoom_data_client", lambda: Client())
    result = app_module.fetch_kiwoom_market_snapshot("turnover")
    assert result["ok"] and result["rows"] == [{"종목명": "FAKE"}]
    assert result["is_mock"] is True
    app_module.fetch_kiwoom_market_snapshot.clear()
