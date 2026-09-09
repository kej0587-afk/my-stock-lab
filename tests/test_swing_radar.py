import pandas as pd

from stock_lab_core.swing_radar import (
    build_swing_radar_df,
    fill_empty_swing_templates,
    get_swing_editor_base_key,
    is_swing_candidate_allowed,
    is_swing_excluded_ticker,
    make_swing_candidate_row,
    merge_swing_editor_with_saved,
    remove_swing_row,
    set_swing_row_status,
)


def test_make_swing_candidate_row_uses_default_template_and_date():
    row = make_swing_candidate_row("Freeport", "FCX", "us_stock", today="2026-09-09")

    assert row["ticker"] == "FCX"
    assert row["name"] == "Freeport"
    assert row["status"] == "진행"
    assert row["decision"] == "관망"
    assert row["last_checked"] == "2026-09-09"
    assert "시스템 승인" in row["idea"]


def test_make_swing_candidate_row_uses_etf_template():
    row = make_swing_candidate_row("Nasdaq 100", "QQQ", "us_etf_nasdaq", is_etf=True, today="2026-09-09")

    assert "ETF" in row["idea"]
    assert "돈흐름" in row["entry_rule"]


def test_fill_empty_swing_templates_fills_required_text_fields():
    df = pd.DataFrame([{"ticker": "FCX", "name": "Freeport"}])

    out = fill_empty_swing_templates(df, today="2026-09-09")

    assert out.iloc[0]["status"] == "진행"
    assert out.iloc[0]["decision"] == "관망"
    assert out.iloc[0]["importance"] == "중"
    assert out.iloc[0]["last_checked"] == "2026-09-09"
    assert out.iloc[0]["entry_rule"]


def test_set_status_and_remove_row_by_normalized_ticker():
    df = pd.DataFrame([make_swing_candidate_row("Freeport", "FCX", today="2026-09-09")])

    hidden = set_swing_row_status(df, "fcx", "숨김", today="2026-09-10")
    removed = remove_swing_row(hidden, "FCX")

    assert hidden.iloc[0]["status"] == "숨김"
    assert hidden.iloc[0]["last_checked"] == "2026-09-10"
    assert removed.empty


def test_swing_candidate_filters_cash_reserve_and_optional_etfs():
    assert is_swing_excluded_ticker("cash")
    assert not is_swing_candidate_allowed("SGOV", bucket="reserve")
    assert not is_swing_candidate_allowed("QQQ", is_etf=True, asset_class="us_etf_nasdaq", include_etf=False)
    assert is_swing_candidate_allowed("QQQ", is_etf=True, asset_class="us_etf_nasdaq", include_etf=True)


def test_build_swing_radar_df_merges_auto_candidates_and_hides_hidden_rows():
    saved = pd.DataFrame(
        [
            make_swing_candidate_row("Old", "OLD", today="2026-09-09"),
            {**make_swing_candidate_row("Hidden", "HID", today="2026-09-09"), "status": "숨김"},
        ]
    )
    auto_candidates = {
        "fcx": {
            "name": "Freeport",
            "ticker": "FCX",
            "asset_class": "us_stock",
            "is_etf": False,
        }
    }

    out = build_swing_radar_df(saved, auto_candidates=auto_candidates, include_hidden=False)

    assert "FCX" in set(out["ticker"])
    assert "HID" not in set(out["ticker"])
    assert "OLD" in set(out["ticker"])


def test_merge_swing_editor_with_saved_removes_deleted_visible_rows():
    saved = pd.DataFrame(
        [
            make_swing_candidate_row("First", "AAA", today="2026-09-09"),
            make_swing_candidate_row("Second", "BBB", today="2026-09-09"),
        ]
    )
    visible = saved.copy()
    edited = pd.DataFrame([make_swing_candidate_row("First changed", "AAA", today="2026-09-09")])

    out = merge_swing_editor_with_saved(saved, edited, visible)

    assert set(out["ticker"]) == {"AAA"}
    assert out.iloc[0]["name"] == "First changed"


def test_swing_editor_base_key_changes_with_flags_and_tickers():
    df = pd.DataFrame([make_swing_candidate_row("First", "AAA", today="2026-09-09")])

    assert get_swing_editor_base_key(df, False, True, False) == "False|True|False|aaa"
