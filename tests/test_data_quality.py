import pandas as pd

from stock_lab_core.data_quality import add_quality_issue, build_asset_quick_quality_report


def test_add_quality_issue_normalizes_blank_ticker():
    issues = []

    add_quality_issue(issues, "주의", "테스트", None, "문제", "조치")

    assert issues == [{
        "등급": "주의",
        "영역": "테스트",
        "티커": "",
        "문제": "문제",
        "확인/조치": "조치",
    }]


def test_asset_quick_quality_report_flags_invalid_inputs_and_sorts_by_severity():
    holdings = pd.DataFrame(
        [
            {"ticker": "VOO", "qty": 1, "avg_price": 10, "target_weight": 40, "account_type": "일반"},
            {"ticker": "VOO", "qty": 2, "avg_price": 20, "target_weight": 50, "account_type": "일반"},
            {"ticker": "", "qty": -1, "avg_price": -10, "target_weight": 120, "account_type": "일반"},
        ]
    )
    dividends = pd.DataFrame(
        [
            {"date": "not-a-date", "ticker": "VOO", "amount": -5},
        ]
    )
    monthly_logs = pd.DataFrame(
        [
            {"month": "2026-05", "total_invested": 100, "evaluated_value": 100, "dividend": 0},
            {"month": "2026-05", "total_invested": -1, "evaluated_value": 100, "dividend": 0},
            {"month": "", "total_invested": 100, "evaluated_value": -10, "dividend": -1},
        ]
    )

    report = build_asset_quick_quality_report(
        {"usdkrw": 0, "seed_money": -1},
        holdings,
        dividends,
        monthly_logs,
    )

    problems = report["문제"].tolist()
    assert problems[:2] == [
        "환율이 0 이하입니다.",
        "시드머니가 음수입니다.",
    ]
    assert "티커가 비어 있습니다." in problems
    assert "보유량이 음수입니다." in problems
    assert "매입가가 음수입니다." in problems
    assert "같은 티커가 2번 등록되어 있습니다." in problems
    assert "배당 날짜 형식이 애매합니다." in problems
    assert "배당금이 음수입니다." in problems
    assert "같은 월이 2번 등록되어 있습니다." in problems
    assert report.iloc[0]["등급"] == "위험"
    first_warning_idx = report.index[report["등급"].eq("주의")][0]
    assert not report.iloc[first_warning_idx:]["등급"].eq("위험").any()
