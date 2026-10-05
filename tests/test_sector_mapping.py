"""Offline checks for researched mappings and explicit sector exclusions."""

import ast
import csv
import json
import re
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

import pytest

from stock_lab_core.formatters import clean_symbol, normalize_ticker


ROOT = Path(__file__).resolve().parents[1]
PROVENANCE_PATH = ROOT / "stock_lab_core/data/sector_benchmark_sources.json"
REVIEW_SYMBOLS = {
    "VIAV", "DDOG", "GFS", "AMAT", "STLD", "FCX", "001450", "0025N0",
    "DELL", "BE", "098120", "MRNA", "CRWD", "HPE", "000500", "096770",
    "003160", "AEHR", "222800", "001820", "108490", "126730", "056190",
    "059120", "030530", "QRVO", "379810", "379800", "069500", "487240",
    "160580",
}
EXCLUDED_SYMBOLS = {"0025N0", "379810", "379800", "069500", "487240", "160580"}
PROVENANCE_FIELDS = {
    "benchmark", "sector", "source_url", "source_name", "verified_on", "proxy_note",
}


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        assert key not in result, f"Duplicate JSON key: {key}"
        result[key] = value
    return result


def _read_json(path):
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)


@pytest.fixture(scope="module")
def sector_map():
    return {
        key: tuple(value)
        for key, value in _read_json(ROOT / "sector_map.json").items()
        if not key.startswith("_")
    }


@pytest.fixture(scope="module")
def provenance():
    return _read_json(PROVENANCE_PATH)


@pytest.fixture(scope="module")
def sector_resolver(sector_map):
    # Execute the production resolver without running Streamlit UI or price I/O.
    tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8-sig"))
    functions = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "get_sector_benchmark_info"
    ]
    assert len(functions) == 1

    def unexpected_fallback(*args, **kwargs):
        pytest.fail(f"Explicit mapping must precede inference: {args}")

    namespace = {
        "normalize_ticker": normalize_ticker,
        "clean_symbol": clean_symbol,
        "SECTOR_BENCHMARK_MAP": sector_map,
        "infer_us_sector_benchmark": unexpected_fallback,
        "get_known_display_name": unexpected_fallback,
        "infer_sector_benchmark_by_name": unexpected_fallback,
    }
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(ROOT / "app.py"), "exec"), namespace)
    return namespace["get_sector_benchmark_info"]


def test_review_cases_have_flat_provenance_and_mapping(sector_map, provenance):
    assert REVIEW_SYMBOLS <= provenance.keys()
    assert REVIEW_SYMBOLS <= sector_map.keys()
    for ticker in REVIEW_SYMBOLS:
        entry = provenance[ticker]
        assert set(entry) == PROVENANCE_FIELDS
        assert sector_map[ticker][0] == entry["benchmark"]
        assert entry["sector"] and entry["source_name"] and entry["proxy_note"]
        assert entry["verified_on"] == "2026-10-06"
        assert date.fromisoformat(entry["verified_on"])
        parsed = urlparse(entry["source_url"])
        assert parsed.scheme == "https" and parsed.netloc
        if entry["benchmark"]:
            assert entry["sector"] == sector_map[ticker][1]
            assert "https://" in entry["proxy_note"]


@pytest.mark.parametrize("ticker", sorted(REVIEW_SYMBOLS))
def test_explicit_mapping_resolves_before_network_or_name_inference(ticker, sector_map, sector_resolver):
    asset_class = "kr_etf" if ticker in EXCLUDED_SYMBOLS else "kr_stock" if ticker[0].isdigit() else "us_stock"
    variants = [ticker, ticker.lower()]
    if ticker[0].isdigit():
        variants += [f"{ticker}.KS", f"{ticker}.KQ", f"{ticker}.kq"]
    for variant in variants:
        assert sector_resolver(variant, asset_class, "KODEX AI전력핵심설비") == sector_map[ticker]


def test_exclusions_are_empty_and_cannot_become_self_benchmarks(sector_map, provenance):
    for ticker in EXCLUDED_SYMBOLS:
        assert sector_map[ticker] == ("", "-")
        assert provenance[ticker]["benchmark"] == ""
        assert "의도적 섹터 비교 제외" in provenance[ticker]["proxy_note"]
    for ticker in REVIEW_SYMBOLS - EXCLUDED_SYMBOLS:
        assert sector_map[ticker][0]
        assert clean_symbol(sector_map[ticker][0]) != ticker


def test_equipment_proxy_and_mixed_asset_exclusion_have_explanatory_sources(provenance):
    bloom = provenance["BE"]
    assert bloom["benchmark"] == "XLI"
    assert "bloomenergy.com" in urlparse(bloom["source_url"]).netloc
    assert "ICLN" in bloom["proxy_note"]
    assert "https://www.ishares.com/us/products/239738/" in bloom["proxy_note"]
    tdf = provenance["0025N0"]
    assert tdf["benchmark"] == ""
    assert tdf["sector"] == "TDF/혼합자산"
    assert "주식혼합 ETF" in tdf["source_name"]


def test_integrated_provenance_loader_handles_suffixes_and_explicit_exclusions(sector_map, provenance):
    from stock_lab_core.relative_strength import get_sector_provenance

    for ticker in REVIEW_SYMBOLS:
        quote_ticker = f"{ticker}.KS" if ticker[0].isdigit() else ticker
        result = get_sector_provenance(quote_ticker, sector_map[ticker][0])
        assert result["섹터분류근거"] == provenance[ticker]["proxy_note"]
        assert result["섹터분류출처"] == provenance[ticker]["source_url"]
        assert result["섹터검증일"] == provenance[ticker]["verified_on"]
    assert get_sector_provenance("BE", "ICLN") == {}


def test_keys_are_uppercase_base_symbols(sector_map, provenance):
    for ticker in sector_map.keys() | provenance.keys():
        assert ticker == ticker.upper()
        assert not ticker.endswith((".KS", ".KQ"))
        assert re.fullmatch(r"[A-Z0-9]+", ticker)


def test_new_benchmarks_are_supported_and_listing_market_matches(sector_map):
    with (ROOT / "stock_lab_core/data/kr_etf_lab.csv").open(encoding="utf-8-sig", newline="") as handle:
        catalog = {row["ticker"]: row["name"] for row in csv.DictReader(handle)}
    tree = ast.parse((ROOT / "stock_lab_core/money_flow.py").read_text(encoding="utf-8-sig"))
    universe = next(
        ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "MONEY_FLOW_UNIVERSE" for target in node.targets)
    )
    supported_us = {row["ticker"] for row in universe if row["구분"] == "미국 섹터"}
    for ticker in REVIEW_SYMBOLS - EXCLUDED_SYMBOLS:
        benchmark = sector_map[ticker][0]
        if ticker[0].isdigit():
            assert benchmark.endswith(".KS")
            assert benchmark in catalog
        else:
            assert benchmark in supported_us
            assert not benchmark.endswith((".KS", ".KQ"))
    assert catalog["396500.KS"] == "TIGER Fn반도체TOP10"
    assert catalog["445290.KS"] == "KODEX 로봇액티브"


@pytest.mark.parametrize(
    ("ticker", "benchmark", "company"),
    [
        ("000500", "487240.KS", "가온전선"),
        ("003160", "396500.KS", "디아이"),
        ("056190", "445290.KS", "에스에프에이"),
        ("030530", "396500.KS", "원익홀딩스"),
        ("160580", "", "구리실물"),
        ("0025N0", "", "TDF2045"),
    ],
)
def test_ambiguous_identities_have_verified_company_and_intended_benchmark(ticker, benchmark, company, sector_map, provenance):
    assert sector_map[ticker][0] == benchmark
    assert company in provenance[ticker]["source_name"]


@pytest.mark.parametrize(
    ("ticker", "benchmark"),
    [("005930", "396500.KS"), ("267260", "487240.KS"), ("MSFT", "XLK"), ("NVDA", "SMH"), ("MAGS", "QQQM")],
)
def test_established_mapping_examples_are_preserved(ticker, benchmark, sector_map):
    assert sector_map[ticker][0] == benchmark
