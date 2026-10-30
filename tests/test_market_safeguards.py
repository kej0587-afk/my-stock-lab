"""Synthetic news and verified-source contracts; no live event constants."""

from copy import deepcopy
from datetime import datetime

import pandas as pd
import pytest

from stock_lab_core.market_safeguards import MAX_NEWS_ROWS, safeguard_events

NOW = datetime.fromisoformat("2026-10-30T13:00:00+09:00")
BUY = "\ucf54\uc2a4\ud53c \ub9e4\uc218 \uc0ac\uc774\ub4dc\uce74 \ubc1c\ub3d9"
SELL = "\ucf54\uc2a4\ud53c \ub9e4\ub3c4 \uc0ac\uc774\ub4dc\uce74 \ubc1c\ub3d9"
CB = "\ucf54\uc2a4\ub2e5 \uae09\ub77d \uc11c\ud0b7\ube0c\ub808\uc774\ucee4 \ubc1c\ub3d9"


def article(title=BUY, **kwargs):
    return dict(title=title, published_at="2026-10-28T10:21:00+09:00",
                publisher="News", link="https://news.example/item", **kwargs)


def official(title=BUY, **kwargs):
    row = article(title, body_status="verified", body_text="2026\ub14410\uc6d428\uc77c " + title,
                  body_source_url="https://kind.krx.co.kr/external/notice.htm")
    row.update(kwargs)
    return row


def test_reported_headline_is_not_official_and_input_is_unchanged():
    source = article()
    before = deepcopy(source)
    rows = safeguard_events([source], NOW)
    assert source == before
    assert len(rows) == 1
    assert (rows[0]["market"], rows[0]["direction"], rows[0]["kind"]) == ("KOSPI", "buy", "sidecar")
    assert rows[0]["status"] == "reported" and rows[0]["date"] == "2026-10-28"
    assert rows[0]["date_basis"] == "publication_date"
    assert rows[0]["coverage"] == "provided_evidence_only"
    assert not rows[0]["price_reaction_verified"]


def test_dedup_prefers_verified_exchange_source_without_losing_citations():
    rows = safeguard_events([article(), article(), official()], NOW)
    assert len(rows) == 1 and rows[0]["status"] == "official"
    assert len(rows[0]["sources"]) == 2
    assert rows[0]["source_url"].startswith("https://kind.krx.co.kr/")


def test_distinct_market_direction_kind_and_date_are_retained():
    rows = safeguard_events([
        article(), article(SELL), article(BUY.replace("\ucf54\uc2a4\ud53c", "\ucf54\uc2a4\ub2e5")), article(CB),
        article(BUY, event_date="2026-10-27"),
    ], NOW)
    assert len(rows) == 5
    cb = next(row for row in rows if row["kind"] == "circuit_breaker")
    assert cb["direction"] == "down"


@pytest.mark.parametrize("suffix", [
    " \uc870\uac74", " \uac00\ub2a5\uc131", " \uc6b0\ub824", "\ud558\uc9c0 \uc54a\uc558\ub2e4",
    " \uc9c1\uc804", "\ub418\uba74 5\ubd84\uac04 \uc815\uc9c0", "\ud560 \uc218 \uc788\ub2e4", " \uae30\uc900", " \ud574\uc81c",
])
def test_conditions_negations_and_speculation_not_events(suffix):
    assert safeguard_events([article(BUY + suffix)], NOW) == []


def test_generic_rule_paragraph_does_not_add_a_sell_event():
    row = official(body_text="2026\ub14410\uc6d428\uc77c " + BUY + ". " + SELL + "\ud55c\ub2e4.")
    events = safeguard_events([row], NOW)
    assert len(events) == 1 and events[0]["direction"] == "buy"


@pytest.mark.parametrize("host", ["news.example", "krx.co.kr.attacker.example", "notkrx.co.kr"])
def test_reporter_citing_exchange_or_spoof_domain_remains_reported(host):
    row = official(body_source_url="https://" + host + "/story", publisher="KRX")
    events = safeguard_events([row], NOW)
    assert events[0]["status"] == "reported"


def test_official_link_and_claimed_status_without_verified_body_not_official():
    row = article(status="official", source_url="https://kind.krx.co.kr/notice")
    assert safeguard_events([row], NOW)[0]["status"] == "reported"


def test_body_explicit_event_date_not_publication_or_report_date():
    row = official(body_text="2026\ub14410\uc6d413\uc77c " + SELL)
    event = safeguard_events([row], NOW)[0]
    assert event["date"] == "2026-10-13" and event["status"] == "official"


def test_yesterday_and_article_day_dates_use_publication_clock():
    row = safeguard_events([article("\uc804\ub0a0 " + BUY)], NOW)[0]
    assert row["date"] == "2026-10-27"
    assert safeguard_events([article("13\uc77c " + SELL)], NOW)[0]["date"] == "2026-10-13"


def test_future_publication_future_event_and_invalid_date_are_omitted():
    future = article()
    future["published_at"] = "2026-10-31T10:00:00+09:00"
    assert safeguard_events([future, article(event_date="2026-10-31"), article(event_date="2026-02-30")], NOW) == []


def test_historical_without_date_not_stamped_with_today():
    assert safeguard_events([article("\uc791\ub144 " + BUY), article("\uc9c0\ub09c\ub2ec " + SELL)], NOW) == []


def test_missing_market_direction_timestamp_or_url_not_invented():
    undated = article()
    undated.pop("published_at")
    no_link = article()
    no_link.pop("link")
    assert safeguard_events([article("\ub9e4\uc218 \uc0ac\uc774\ub4dc\uce74 \ubc1c\ub3d9"),
                             article("\ucf54\uc2a4\ud53c \uc0ac\uc774\ub4dc\uce74 \ubc1c\ub3d9"), undated, no_link], NOW) == []


def test_ambiguous_markets_do_not_make_cartesian_events():
    assert safeguard_events([article("\ucf54\uc2a4\ub2e5 " + BUY)], NOW) == []


def test_verified_body_facts_contract():
    row = article(body_status="verified", body_source_url="https://kind.krx.co.kr/notice",
                  body_facts=[dict(text=BUY, event_date="2026-10-28")])
    event = safeguard_events([row], NOW)[0]
    assert event["status"] == "official" and event["evidence_level"] == "verified_body"


def test_verified_body_rebuttal_does_not_fall_back_to_headline():
    row = official(body_text=BUY + "\ud558\uc9c0 \uc54a\uc558\ub2e4")
    assert safeguard_events([row], NOW) == []


def test_future_body_version_cannot_be_official():
    row = official(body_modified_at="2026-10-31T00:00:00+09:00")
    assert all(e["status"] == "reported" for e in safeguard_events([row], NOW))


def test_empty_dataframe_dict_and_generator_contracts():
    assert safeguard_events(None, NOW) == []
    assert safeguard_events(pd.DataFrame(), NOW) == []
    assert len(safeguard_events(pd.DataFrame([article(), article()]), NOW)) == 1
    assert len(safeguard_events(article(), NOW)) == 1
    count = []

    def unbounded():
        while True:
            count.append(1)
            yield article()

    assert len(safeguard_events(unbounded(), NOW)) == 1
    assert len(count) == MAX_NEWS_ROWS


def test_kst_date_not_utc_calendar_day():
    row = article()
    row["published_at"] = "2026-10-27T23:00:00+00:00"
    assert safeguard_events(row, NOW)[0]["date"] == "2026-10-28"


def test_condition_before_trigger_is_not_an_event():
    condition = "\ucf54\uc2a4\ud53c \ub9e4\uc218 \uc0ac\uc774\ub4dc\uce74\ub294 1\ubd84 \uc9c0\uc18d\ub420 \uacbd\uc6b0 \ubc1c\ub3d9\ud558\ub294 \uc7a5\uce58\ub2e4"
    assert safeguard_events([official(body_text=condition)], NOW) == []


def test_explicit_date_cannot_override_a_conflicting_body_date():
    assert safeguard_events([official(event_date="2026-10-27")], NOW) == []


def test_only_exchange_hostname_with_body_date_is_official():
    row = official(body_text=BUY)
    assert safeguard_events([row], NOW)[0]["status"] == "reported"


def test_dont_infer_circuit_breaker_level_or_direction():
    row = article(CB.replace("\uae09\ub77d ", ""))
    event = safeguard_events([row], NOW)[0]
    assert event["direction"] == "unknown" and "level" not in event


def test_existing_article_evidence_contract_and_unrelated_facts():
    row = official(body_text="", body_facts=[dict(evidence="2026-10-28 " + BUY)])
    assert safeguard_events([row], NOW)[0]["status"] == "official"
    row["body_facts"] = [dict(evidence="earnings growth", summary="positive earnings")]
    assert safeguard_events([row], NOW)[0]["status"] == "reported"


def test_duration_is_not_event_day_and_previous_trading_day_not_guessed():
    assert safeguard_events([article("11\uc77c \ub9cc\uc5d0 " + BUY)], NOW)[0]["date"] == "2026-10-28"
    assert safeguard_events([article("\uc804 \uac70\ub798\uc77c " + BUY)], NOW) == []


def test_invalid_body_timestamp_or_url_cannot_be_official():
    for row in [official(body_modified_at="invalid"), official(body_source_url="invalid")]:
        assert safeguard_events([row], NOW)[0]["status"] == "reported"
