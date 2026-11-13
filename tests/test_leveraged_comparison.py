"""Exact session endpoints, missing inputs, untouched criteria and request scope."""

import ast
from copy import deepcopy
from pathlib import Path
import subprocess
from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest

from stock_lab_core import leveraged_comparison as module, leveraged_watch
from stock_lab_core.leveraged_product_view import render_watch_basis, watch_display_rows
from tests.test_leveraged_product_view import UI
from tests.test_leveraged_watch import baseline_scope


@pytest.fixture
def context():
    return module.comparison_context("SOXL", now="2026-11-13T13:00:00+09:00")


@pytest.fixture
def callbacks():
    original = baseline_scope()
    return {"pct_text": original["_leveraged_precision_pct_text"],
            "judge": original["_leveraged_precision_proxy_judgement"]}


def history(context, market="US"):
    index = context["sessions"][market].index[-30:]
    return pd.DataFrame({"Close": np.arange(len(index), dtype=float) + 100}, index=index)


def test_regular_returns_ignore_future_partial_and_quote(context, callbacks):
    frame = history(context)
    before = frame.copy(deep=True)
    result = module.completed_comparison_row(("SOXX", "기초 ETF", "반도체"), frame, context=context, **callbacks)
    frame.loc[pd.Timestamp("2026-11-13")] = 9999
    actual = module.completed_comparison_row(("SOXX", "기초 ETF", "반도체"), frame, context=context, **callbacks)
    assert actual == result
    for key, bars in (("_1d", 1), ("_1w", 5), ("_1m", 21)):
        assert actual[key] == pytest.approx((before.Close.iloc[-1] / before.Close.iloc[-bars - 1] - 1) * 100)
    assert actual["판정"] == callbacks["judge"](actual["_1d"], actual["_1w"], actual["_1m"])
    assert actual["종료 시각"] == "2026-11-13 06:00 KST"
    assert actual["_comparison_windows"]["1W"]["start_day"] == "2026-11-05"


@pytest.mark.parametrize("change", ["stale_end", "missing_start", "duplicate", "pending", "zero", "nan", "short"])
def test_missing_endpoints_never_fallback(context, callbacks, change):
    frame = history(context)
    if change == "stale_end": frame = frame.iloc[:-1]
    if change == "missing_start": frame = frame.drop(frame.index[-6])
    if change == "duplicate": frame = pd.concat([frame, frame.iloc[[-6]]])
    if change == "pending": frame.attrs["report_close_pending_date"] = frame.index[-1].strftime("%Y-%m-%d")
    if change == "zero": frame.iloc[-6, 0] = 0
    if change == "nan": frame.iloc[-6, 0] = np.nan
    if change == "short": frame = frame.iloc[-2:]
    row = module.completed_comparison_row(("SOXX", "기초 ETF", "반도체"), frame, context=context, **callbacks)
    assert np.isnan(row["_1w"])
    assert "1W 종가 미확보" in row["자료 상태"]
    assert watch_display_rows("SOXL", [row])[0]["회복 평균 반영"] == "미포함"


def test_kr_crypto_separate_and_basket_membership_unchanged(context, callbacks):
    kr = module.completed_comparison_row(("418660.KS", "비교 상품", "ETF"), history(context, "KR"), context=context, **callbacks)
    assert kr["종료 시각"] == "2026-11-12 15:30 KST"
    assert "미국과 시각 다름" in kr["비교 기준"]
    btc = module.completed_comparison_row(("BTC-USD", "기초 자산", "현물"), history(context), context=context, **callbacks)
    assert np.isnan(btc["_1w"]) and "동시각 미확보" in btc["비교 기준"]
    rows = [module.completed_comparison_row((t, role, t), history(context), context=context, **callbacks)
            for t, role in [("BITX", "비교 상품"), ("IBIT", "기초 ETF"), ("QQQ", "시장 환경"), ("UUP", "시장 환경")]]
    assert [r["회복 평균 반영"] for r in watch_display_rows("BITX", rows)] == ["미포함", "포함", "포함", "포함"]


@pytest.mark.parametrize("now,day,end", [
    ("2026-11-13T21:10:00Z", "2026-11-12", "2026-11-13 06:00 KST"),
    ("2026-11-13T21:15:00Z", "2026-11-13", "2026-11-14 06:00 KST"),
    ("2026-11-14T20:00:00Z", "2026-11-13", "2026-11-14 06:00 KST"),
    ("2026-11-26T22:00:00Z", "2026-11-25", "2026-11-26 06:00 KST"),
    ("2026-11-27T18:15:00Z", "2026-11-27", "2026-11-28 03:00 KST"),
    ("2026-10-30T20:15:00Z", "2026-10-30", "2026-10-31 05:00 KST"),
])
def test_calendar_dst_holiday_early_close_and_grace(now, day, end, callbacks):
    ctx = module.comparison_context("SOXL", now=now)
    result = module.completed_comparison_row(("SOXX", "기초 ETF", ""), history(ctx), context=ctx, **callbacks)
    assert result["종료 시각"] == end
    assert result["_comparison_windows"]["1D"]["end_day"] == day


def test_calendar_failure_stays_unknown(callbacks):
    ctx = module.comparison_context("SOXL", now="2026-11-13T00:00Z", schedule_loader=Mock(side_effect=ValueError("broken")))
    result = module.completed_comparison_row(("SOXX", "기초 ETF", ""), pd.DataFrame({"Close": [1, 2]}), context=ctx, **callbacks)
    assert np.isnan(result["_1d"]) and "거래소 달력 미연결" in result["자료 상태"]
    with pytest.raises(ValueError): module.comparison_context("SOXL", now="2026-11-13")


@pytest.mark.parametrize("profile,ticker", list(module.PRODUCTS.items()))
@pytest.mark.parametrize("batched", [False, True])
def test_builders_no_live_requests_exact_rows_once_and_input_immutable(monkeypatch, context, callbacks, profile, ticker, batched):
    monkeypatch.setattr(module, "comparison_context", lambda _: context)
    frame = history(context)
    saved = frame.copy(deep=True)
    quote = Mock(side_effect=AssertionError("live quote must not enter completed returns"))
    load = Mock(return_value=frame)
    batch = Mock(side_effect=lambda tickers, period: {t: frame for t in tickers})
    watch = [("IBIT", "기초 ETF", "proxy"), ("QQQ", "시장 환경", "market")]
    args = dict(load_quote=quote, load_history=load, comparison_profile=profile, comparison_ticker=ticker, **callbacks)
    with leveraged_watch.leveraged_watch_history_scope():
        rows = leveraged_watch.build_leveraged_watch_rows_batched(watch, load_batch=batch, **args) if batched else leveraged_watch.build_leveraged_watch_rows(watch, parallel=False, **args)
    quote.assert_not_called()
    assert [r["Ticker"] for r in rows] == [ticker, "IBIT", "QQQ"]
    assert len(watch) == 2
    assert batch.call_count == int(batched)
    assert load.call_count == (0 if batched else 3)
    pd.testing.assert_frame_equal(frame, saved)
    for row in rows:
        assert row["_comparison_version"] == module.VERSION


@pytest.mark.parametrize("profile,ticker", [("BITX", "BITU"), ("NASDAQ100_2X_KR", "OTHER"), ("QLD", "QLD")])
def test_shared_profile_does_not_insert_wrong_fund(profile, ticker):
    assert module.exact_profile(profile, ticker) == ""
    assert module.comparison_entries([], module.exact_profile(profile, ticker)) == []


def test_compact_ui_has_start_end_and_no_mixed_quote_claim(context, callbacks):
    rows = [module.completed_comparison_row(("SOXL", "비교 상품", "SOXL"), history(context), context=context, **callbacks)]
    before = deepcopy(rows)
    ui = UI()
    render_watch_basis(ui, "SOXL", rows)
    assert rows == before
    assert len(ui.tables) == 2
    assert "기준 종가" in ui.tables[0][0] and "현재가" not in ui.tables[0][0]
    assert ui.tables[1][1]["기간"] == "1W"
    assert "혼합하지 않습니다" in " ".join(ui.text)


def test_exact_adapter_preserves_immutable_calculation_bodies():
    from tests.leveraged_view_ast_contract import before_leveraged_product_view
    root = Path(__file__).resolve().parents[1]
    old = ast.parse(subprocess.check_output(["git", "show", "9e07a76e:app.py"], cwd=root, encoding="utf-8-sig"))
    new = ast.parse((root / "app.py").read_text(encoding="utf-8-sig"))
    for name in ("build_leveraged_precision_watch_rows", "build_leveraged_precision_state"):
        before = next(n for n in old.body if isinstance(n, ast.FunctionDef) and n.name == name)
        after = next(n for n in new.body if isinstance(n, ast.FunctionDef) and n.name == name)
        assert ast.dump(before_leveraged_product_view(after)) == ast.dump(before)
        altered = deepcopy(after)
        altered.body += ast.parse("underlying_1w_avg = 999").body
        assert ast.dump(before_leveraged_product_view(altered)) != ast.dump(before)


def test_deployment_old_module_defers_instead_of_typeerror(monkeypatch):
    node = next(n for n in ast.parse(Path("app.py").read_text(encoding="utf-8-sig")).body
                if isinstance(n, ast.FunctionDef) and n.name == "build_leveraged_precision_watch_rows")
    node.decorator_list = []
    st = Mock()
    monkeypatch.delattr(leveraged_watch, "SESSION_COMPARISON_VERSION")
    scope = {"st": st}
    exec(compile(ast.Module(body=[node], type_ignores=[]), "app.py", "exec"), scope)
    assert scope[node.name]("SOXL", comparison_ticker="SOXL") == []
    assert "비교값 사용 보류" in st.warning.call_args.args[0]


def test_real_streamlit_comparison_tables():
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_string('''import streamlit as st
import numpy as np
import pandas as pd
from stock_lab_core.leveraged_comparison import comparison_context, completed_comparison_row
from stock_lab_core.leveraged_product_view import render_watch_basis
ctx = comparison_context("BITX", now="2026-11-13T13:00+09:00")
rows = []
for t, market in [("BITX", "US"), ("IBIT", "US"), ("418660.KS", "KR"), ("BTC-USD", "US")]:
    dates = ctx["sessions"][market].index[-30:]
    frame = pd.DataFrame({"Close": np.arange(len(dates)) + 100.0}, index=dates)
    rows.append(completed_comparison_row((t, "비교 상품", t), frame, context=ctx,
        pct_text=lambda v: "-" if pd.isna(v) else f"{v:+.1f}%", judge=lambda *args: "test"))
render_watch_basis(st, "BITX", rows)
''').run()
    assert not app.exception
    assert len(app.dataframe) == 4
    assert any("미국과 별도 시각" in m.value for m in app.markdown)
