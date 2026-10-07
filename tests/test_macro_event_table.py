from datetime import date

import pandas as pd


def test_macro_event_table_shows_result_and_market_interpretation(app_module, monkeypatch):
    today = date(2026, 10, 7)

    monkeypatch.setattr(
        app_module,
        "build_macro_event_candidates",
        lambda _today: [
            {
                "date": today.isoformat(),
                "end_date": today.isoformat(),
                "event": "미국 CPI 발표",
                "market": "미국 주식/달러/금리",
                "actual": "3.5%",
                "forecast": "3.2%",
                "previous": "3.1%",
                "weight": 1.0,
                "pre_days": 0,
                "post_days": 1,
                "source": "테스트",
            }
        ],
    )

    event_df, event_risk, event_count = app_module.build_macro_event_risk_table(today)

    assert event_risk == 1.25
    assert event_count == 1
    assert "결과" in event_df.columns
    assert "주식시장 해석" in event_df.columns
    assert "확인포인트" in event_df.columns
    assert "영향" not in event_df.columns
    assert "해석" not in event_df.columns
    assert "실제 3.5%" in event_df.loc[0, "결과"]
    assert "금리와 달러 상승 압력" in event_df.loc[0, "주식시장 해석"]


def test_macro_event_table_marks_pre_result_events(app_module, monkeypatch):
    today = date(2026, 10, 7)

    monkeypatch.setattr(
        app_module,
        "build_macro_event_candidates",
        lambda _today: [
            {
                "date": date(2026, 10, 9).isoformat(),
                "end_date": date(2026, 10, 9).isoformat(),
                "event": "미국 고용지표",
                "market": "미국 주식/달러/금리",
                "weight": 1.0,
                "pre_days": 3,
                "post_days": 1,
                "source": "테스트",
            }
        ],
    )

    event_df, event_risk, event_count = app_module.build_macro_event_risk_table(today)

    assert event_risk == 1.0
    assert event_count == 1
    assert event_df.loc[0, "상태"] == "임박"
    assert event_df.loc[0, "결과"].startswith("발표 임박")
    assert "결과가 나오기 전" in event_df.loc[0, "주식시장 해석"]


def test_macro_analysis_empty_price_data_is_cautious_not_safe(app_module, monkeypatch):
    if hasattr(app_module.get_macro_analysis, "clear"):
        app_module.get_macro_analysis.clear()
    monkeypatch.setattr(app_module.yf, "download", lambda *args, **kwargs: pd.DataFrame())
    monkeypatch.setattr(app_module, "build_macro_event_risk_table", lambda *args, **kwargs: (pd.DataFrame(), 0.0, 0))

    results, final_macro_risk, macro_penalty, move_val = app_module.get_macro_analysis()

    assert results == {}
    assert final_macro_risk >= 1.5
    assert macro_penalty >= 0.5
    assert pd.isna(move_val)
