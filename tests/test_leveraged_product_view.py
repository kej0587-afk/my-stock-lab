"""Display adapters must not mutate the decision inputs or their basket."""

from copy import deepcopy
from contextlib import nullcontext

import pytest

from stock_lab_core.leveraged_product_view import (
    PRODUCTS, channel_basis_note, render_product_basis, render_watch_basis,
    watch_display_rows,
)


@pytest.mark.parametrize("ticker", ["SOXL", "RAM", "BITX", "418660.KS"])
def test_channel_uses_own_prices_not_scaled_proxy(ticker):
    note = channel_basis_note(ticker)
    assert ticker in note
    assert "자체 가격" in note and "자동 피벗" in note
    assert "단타 검증 결과가 아닙니다" in note


@pytest.mark.parametrize("ticker", ["MSFT", "SOXX", "BITU", "", None])
def test_product_facts_are_not_guessed_from_other_product(ticker):
    assert channel_basis_note(ticker) == ""


def row(ticker, role, value=12.25):
    return {"Ticker": ticker, "구분": role, "1D": "+1.0%", "1W": "+12.2%",
            "1M": "+3.0%", "판정": "관찰", "_1d": 1.0, "_1w": value, "_1m": 3.0}


def test_display_corrects_smh_role_without_removing_it_from_existing_basket():
    raw = [row("SOXX", "기초 ETF"), row("SMH", "기초 ETF"), row("NVDA", "대표축")]
    before = deepcopy(raw)
    result = watch_display_rows("SOXL", raw)
    assert raw == before
    assert result[0]["구분"] == "동일 지수 비교 ETF"
    assert result[1]["구분"] == "다른 반도체 비교 ETF"
    assert [r["회복 평균 반영"] for r in result] == ["포함", "포함", "미포함"]
    assert all(not any(k.startswith("_") for k in r) for r in result)
    assert result[0]["5봉 기준*"] == before[0]["1W"]
    assert result[0]["판정"] == before[0]["판정"]
    assert "1W" not in result[0]


def test_bitcoin_calendar_and_existing_basket_are_disclosed_not_changed():
    raw = [row("BTC-USD", "기초 자산"), row("IBIT", "기초 ETF"), row("QQQ", "시장 환경"), row("UUP", "시장 환경")]
    result = watch_display_rows("BITX", raw)
    assert [r["회복 평균 반영"] for r in result] == ["미포함", "포함", "포함", "포함"]
    assert result[1]["구분"] == "현물 비교 ETF"
    assert "선물" in PRODUCTS["BITX"][0]
    assert "주말" in PRODUCTS["BITX"][2]


@pytest.mark.parametrize("value", [None, float("nan"), float("inf"), "bad"])
def test_missing_returns_are_not_claimed_as_basket_contributors(value):
    assert watch_display_rows("SOXL", [row("SOXX", "기초 ETF", value)])[0]["회복 평균 반영"] == "미포함"


class UI:
    def __init__(self):
        self.text = []
        self.tables = []

    def markdown(self, value): self.text.append(value)
    def caption(self, value): self.text.append(value)
    def info(self, value): self.text.append(value)
    def table(self, value): self.tables.append(value)
    def dataframe(self, value, **kwargs): self.tables.append(value)
    def expander(self, *args, **kwargs): return nullcontext()


@pytest.mark.parametrize("ticker", ["SOXL", "RAM", "BITX", "418660.KS"])
def test_render_handles_missing_data_without_requesting_quotes(ticker):
    ui = UI()
    render_product_basis(ui, ticker)
    render_watch_basis(ui, ticker, [])
    text = " ".join(ui.text)
    assert "데이터가 아직 없습니다" in text
    assert "동일 세션은 미검증" in text
    assert "주말" in text
    assert len(ui.tables) == 1
    assert len(ui.tables[0]) == 3
    if ticker == "BITX":
        assert "BTC 현물 자체는 현재 회복 평균에 포함되지 않습니다" in text


def test_issuer_target_is_not_confused_with_sox_or_soxx_fund():
    assert "NYSE Semiconductor Index" in PRODUCTS["SOXL"][0]
    assert "SOX(PHLX)는 별도 지수" in PRODUCTS["SOXL"][1]
    assert "DRAM ETF" in PRODUCTS["RAM"][0]
    assert "합성" in PRODUCTS["418660"][0]
    assert "원/달러 환율 그 자체가 아닙니다" in PRODUCTS["418660"][1]


def test_actual_streamlit_renderer():
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_string('''import streamlit as st
from stock_lab_core.leveraged_product_view import render_product_basis, render_watch_basis
for t in ["SOXL", "RAM", "BITX", "418660.KS"]:
    render_product_basis(st, t)
    render_watch_basis(st, t, [{"Ticker":"IBIT", "구분":"기초 ETF", "1D":"-1%", "1W":"-3%", "1M":"-8%", "_1w":-3.0}])
''').run()
    assert not app.exception
    assert len(app.table) == 4 and len(app.dataframe) == 4


def test_historical_contract_does_not_mask_calculation_changes():
    import ast
    from pathlib import Path
    import subprocess
    from tests.leveraged_view_ast_contract import before_leveraged_product_view
    root = Path(__file__).resolve().parents[1]
    before = ast.parse(subprocess.check_output(["git", "show", "21428d1b:app.py"], cwd=root, encoding="utf-8-sig"))
    after = ast.parse((root / "app.py").read_text(encoding="utf-8-sig"))
    for name in ("render_leveraged_etf_precision_panel", "render_precision_candlestick_chart"):
        old = next(n for n in before.body if isinstance(n, ast.FunctionDef) and n.name == name)
        new = next(n for n in after.body if isinstance(n, ast.FunctionDef) and n.name == name)
        assert ast.dump(before_leveraged_product_view(new)) == ast.dump(old)
        altered = deepcopy(new)
        altered.body += ast.parse("rr = 999").body
        assert ast.dump(before_leveraged_product_view(altered)) != ast.dump(old)
