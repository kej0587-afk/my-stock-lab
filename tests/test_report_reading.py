"""Reader layout contracts: preserve dated data and decisions, shorten main path."""
from copy import deepcopy
from datetime import datetime

import pytest

from stock_lab_core.report_reading import AUDIT_TITLE, compose_reading_report, tables
from stock_lab_core.report_view import COLLAPSED_SECTIONS, split_report_sections
from stock_lab_core.report_brief import build_news_brief

NOW = datetime.fromisoformat("2026-11-15T18:00:00+09:00")
CONTEXT = {"sessions": {"KR": "2026-11-13", "US": "2026-11-13"}, "prices": {
    "^KS11": {"date": "2026-11-13", "return": .0123},
    "^GSPC": {"date": "2026-11-13", "return": -.004},
}}
REPORT = """# Stock Lab 자동 뉴스픽 · fixture
신규매수 허용 0개 / 보고서 매크로 스트레스 74 경고
## 지수·매크로 한눈에
대상 | 수준 | 등락·비교 기준 | 기준일·시각 | 출처
--- | --- | --- | --- | ---
코스피(^KS11) | 6,000.00 pt | +1.23% · 정규장 종가·전 거래일 대비 | 2026-11-13 | fixture
10Y 금리(^TNX) | 5.15 % | +2.20% · 1개월 변화 | 2026-11-13 | fixture
## 내 보유 종목 영향
구분 | 계좌 기여(추정) | 연결 비중 | 시작 종가일 → 관측일
--- | --- | --- | ---
연결분 기여(전체 추정 아님) | -0.17%p | 87.5% | 전체 추정 보류: 연결 90% 미만

종목 | 기준일 일간(실제) | 배수 참고(추정) | 당일 현재(실제) | 상태/사유
--- | --- | --- | --- | ---
Fixture(SOXL) | -11.00% (2026-11-13 확정 종가) | -11.01% 추정 | 해당없음 | 방어우선 · 레버리지 보유
## 관심 후보 상위 3개
후보·개별 신호·실행 상태 | 게이트 근거 | 해제 조건
--- | --- | ---
MSFT · 방어우선 | 시장방어 | 시장 게이트 해제 후 재계산
## 다가오는 일정
일정·남은 일수 | 발표·콜 시각 | 공식 출처
--- | --- | ---
CPI | 2026-12-10 | fixture

**기업 실적 촉매**
기업·상태 | 발표일 / 콜 시각 | 근거·연결 범위
--- | --- | ---
NVDA · 예정 | 2026-11-17 | 공식 IR
MSFT · 공식 결과 발표 확인 | 2026-10-28 | 공식 IR
## 주도 업종 교체 관측
반도체·AI가 회복하는지와 다른 업종으로 강세가 확산되는지를 나누어 봅니다.
시장·업종·기준일 | 실제 수익률 5일 / 20일 / 63일 | RS 변화 5일 / 20일 | 관측 해석 | 다음 확인
--- | --- | --- | --- | ---
US 기술 · 2026-11-13 | -5% / -3% / +1% | -2% / -1% | 상대 약세 | 차기 종가 확인
## 경제지표
PPI 근거 · 2026-11-13 원문
"""


def render(context=None, news=()):
    return compose_reading_report(REPORT, context=context or deepcopy(CONTEXT), news=news, summary_rows=[], now=NOW)


def test_reading_order_keeps_one_report_and_unique_audit_evidence():
    output = render()
    parts = split_report_sections(output.split("## " + AUDIT_TITLE, 1)[0])
    # Quick summary -> market body -> account -> schedule (2026-11-24 report-overhaul request).
    assert [title for title, _ in parts][1:] == ["빠른 요약", "미국 시황", "한국 시황", "세계 시장과 국가 ETF",
        "매크로", "물가·고용·소비·경기", "관측실 지표 연결 상태", "이번 주 테마 5개", "돈흐름 · 업종 순환",
        "주요 기업과 사건", "오늘의 판단", "포트폴리오 · 교체 검토", "다음 일정", "마무리 · 보유 종목 영향과 다음 확인 사항"]
    main, audit = output.split("## " + AUDIT_TITLE, 1)
    assert "반도체·AI가 회복하는지와" not in main
    assert output.count("# Stock Lab 자동 뉴스픽 · fixture") == 1
    assert "PPI 근거 · 2026-11-13 원문" in audit
    assert "-11.01% 추정" in main  # Holdings retain their session/comparison qualifiers.
    assert "Fixture(SOXL) |" not in audit
    assert "MSFT · 공식 결과 발표 확인" in audit
    assert "코스피(^KS11)" not in audit
    assert output.count("MSFT · 방어우선 | 시장방어 | 시장 게이트 해제 후 재계산") == 1
    assert output.count("신규매수 허용 0개 / 보고서 매크로 스트레스 74 경고") == 1
    assert AUDIT_TITLE in COLLAPSED_SECTIONS


def test_units_dates_partial_coverage_and_gate_do_not_disappear():
    sections = dict(split_report_sections(render()))
    assert "5.15 % | +2.20% · 1개월 변화 | 2026-11-13" in sections["매크로"]
    assert "코스피(^KS11)" not in sections["매크로"]
    assert "5.15" not in sections["빠른 요약"] and "지수" not in sections  # index table once, in 빠른 요약
    assert sections["빠른 요약"].count("코스피(^KS11)") == 1
    assert "**내 보유 종목 영향** · 비중 상위 1개" in sections["빠른 요약"]
    assert "- Fixture(SOXL) · -11.00% (2026-11-13 확정 종가) · 방어우선 · 레버리지 보유" in sections["빠른 요약"]
    portfolio = sections["포트폴리오 · 교체 검토"]
    assert "전체 추정 보류: 연결 90% 미만" in portfolio
    assert "실제 계좌 수익률이 아닙니다" in portfolio
    assert "-11.00% (2026-11-13 확정 종가)" in portfolio
    assert "방어우선 · 레버리지 보유" in portfolio
    assert "시장 게이트 해제 후 재계산" in portfolio
    assert "배수 참고" in portfolio and "당일 현재" in portfolio
    assert "NVDA · 예정" in sections["다음 일정"]
    assert "MSFT · 공식 결과" not in sections["다음 일정"]


@pytest.mark.parametrize("current", [
    "데이마켓(야간) -3.45% · 2026-11-16 11:41 KST · 별도 세션·미확정",
    "프리마켓 +1.25% · 2026-11-16 19:10 KST · 별도 세션·미확정",
    "마감 후 -2.30% · 2026-11-14 07:10 KST · 별도 세션·미확정",
    "+0.00% (2026-11-16 장중 진행·확정 아님; 2026-11-16 11:41 KST)",
    "정규장 외 · 데이마켓/시간외 시세 미연결: 제공처 응답·시각 미확인",
    "시각 확인 가능한 시세 미수집",
    "해당없음",
])
def test_reader_preserves_every_holding_cell_even_without_numeric_quote(current):
    from stock_lab_core.report_reading import _portfolio_lines
    source = REPORT.split("## 내 보유 종목 영향\n", 1)[1].split("## 관심 후보", 1)[0]
    source = source.replace("-11.01% 추정", "누적 비교 보류: 동일 시각 자료 미연결")
    source = source.replace("해당없음", current)
    sections = {"내 보유 종목 영향": source}
    original = deepcopy(sections)
    output = "\n".join(_portfolio_lines(sections))
    expected = next(table for table in tables(source) if table[0][0] == "종목")
    assert expected in tables(output)
    assert sections == original


def test_unknown_holdings_schema_is_preserved_not_projected_by_column_count():
    from stock_lab_core.report_reading import _portfolio_lines
    source = "종목 | 조회시각 | 공급자 | 연결 상태 | 판정 | 새 열\n--- | --- | --- | --- | --- | ---\nTEST | 미확인 | fixture | 미연결 | 방어우선 | 원문 유지"
    output = "\n".join(_portfolio_lines({"내 보유 종목 영향": source}))
    assert tables(source)[0] in tables(output)


def test_missing_session_survives_streamlit_render_and_rerun():
    from streamlit.testing.v1 import AppTest
    from stock_lab_core.report_reading import _portfolio_lines

    def report_app(report):
        from stock_lab_core.report_view import render_market_report
        render_market_report(report)

    source = REPORT.split("## 내 보유 종목 영향\n", 1)[1].split("## 관심 후보", 1)[0]
    source = source.replace("해당없음", "정규장 외 · 시간외 시세 미연결: 시각 미확인")
    report = "\n".join(_portfolio_lines({"내 보유 종목 영향": source}))
    app = AppTest.from_function(report_app, args=(report,)).run()
    for _ in range(2):
        assert not app.exception
        shown = "\n".join(item.value for item in app.markdown)
        assert "2026-11-13 확정 종가" in shown and "시간외 시세 미연결: 시각 미확인" in shown
        assert "방어우선 · 레버리지 보유" in shown
        app.run()


def article(**kwargs):
    return dict(title="NVIDIA announces chip supply update", publisher="Reuters",
        link="https://www.reuters.com/fixture", market="US", session_date="2026-11-13",
        news_bucket="session_news", published_at="2026-11-13T15:00:00-05:00", **kwargs)


@pytest.mark.parametrize("mutations", [
    {"session_date": "2026-11-12"}, {"news_bucket": "next_session_news"},
    {"published_at": "2026-11-16T01:00:00+09:00"},
])
def test_compact_news_obeys_same_session_future_and_post_close_filters(mutations):
    row = article()
    row.update(mutations)
    result = build_news_brief(CONTEXT, [row], [], NOW, compact=True)
    assert not result["article_keys"]


def test_title_only_claim_not_promoted_and_inputs_immutable():
    context, rows = deepcopy(CONTEXT), [article()]
    original = deepcopy((context, rows))
    result = render(context, rows)
    main = result.split("## " + AUDIT_TITLE)[0]
    assert "제목 확인·기사 주장" in main
    assert "본문 근거:" not in main
    assert (context, rows) == original


def test_compact_render_keeps_same_selected_articles_as_full_brief():
    rows = [article()]
    full = build_news_brief(CONTEXT, rows, [], NOW)
    compact = build_news_brief(CONTEXT, rows, [], NOW, compact=True)
    assert full["article_keys"] == compact["article_keys"]
    assert len("\n".join(compact["lines"])) < len("\n".join(full["lines"]))


def test_empty_report_still_has_named_missing_states():
    result = compose_reading_report("# Empty", context={}, news=[], summary_rows=[], now=NOW)
    assert "종가 미수집" in result and "업종 비교 자료 미연결" in result


def test_summary_citation_does_not_hide_article_details_from_main(monkeypatch):
    row = article()
    monkeypatch.setattr("stock_lab_core.report_market_summary.market_summary", lambda *a: {
        "market_readings": {"US": "시장 혼조 [배경 보도](" + row["link"] + ")"}, "background_news": [row]})
    main = render(news=[row]).split("## " + AUDIT_TITLE, 1)[0]
    assert row["title"] in main and "제목 확인·기사 주장" in main


def test_pipe_prose_is_not_a_table():
    assert tables("this | is prose\nnot a table\nnext | line") == []


def test_power_company_name_does_not_become_oil_sector_cause():
    from stock_lab_core.report_presentation import sector_related_news
    row = article()
    row["title"] = "Has Constellation Energy (CEG) Fallen Below Fair Value After Raising Earnings Guidance?"
    assert not sector_related_news("XLE", "2026-11-13", [row])
    row["title"] = "Constellation Energy comments on oil prices and energy stocks"
    assert sector_related_news("XLE", "2026-11-13", [row])


def test_macro_summary_only_promotes_recent_verified_period_rows():
    from stock_lab_core.report_reading import _recent_releases
    current = dict(indicator="US_PPI", period="2026-10", basis="MoM", unit="%", actual=.3,
                   previous=.2, status="released", release_at="2026-11-13", source_url="https://www.bls.gov/ppi/")
    old = dict(current, indicator="US_CPI", release_at="2026-11-01")
    context = dict(CONTEXT, economic_releases=[old, current])
    source = "지표 | 발표치 | 예상 | 이전 | 해석 | 반응\n--- | --- | --- | --- | --- | ---\nCPI | 4% | 3% | 2% | old | old\nPPI | 0.3% | 0.4% | 0.2% | pressure | +2bp"
    result = "\n".join(_recent_releases({"경제지표": source}, context, NOW))
    assert "PPI |" not in result  # date and source are attached to its label
    assert "발표 2026-11-13" in result and "0.3% | 0.4% | 0.2%" in result
    assert "+2bp" in result and result.count("0.3% | 0.4% | 0.2%") == 1
    assert "CPI" not in result
    context["economic_releases"] = [old, dict(current, status="stale")]
    fallback = "\n".join(_recent_releases({"경제지표": source}, context, NOW))
    # Nothing recent: the last confirmed publication is shown, labelled as older;
    # the stale row is still never promoted.
    assert "최근 3거래일 안 새 발표 없음" in fallback and "최근 발표 · 변화가 큰" not in fallback
    assert "발표 2026-11-01" in fallback and "4% | 3% | 2%" in fallback
    assert "0.3% | 0.4% | 0.2%" not in fallback


def test_release_fallback_orders_by_date_and_skips_undated_or_future_rows():
    from stock_lab_core.report_reading import _recent_releases
    base = dict(period="2026-10", basis="MoM", unit="%", actual=.3, previous=.2, status="released",
                source_url="https://www.bls.gov/")
    rows = [dict(base, indicator="US_CPI", release_at="2026-11-01"),
            dict(base, indicator="US_PAYROLLS", release_at=""),
            dict(base, indicator="KR_EXPORTS", release_at="2026-11-05"),
            dict(base, indicator="US_PPI", release_at="2026-11-30")]
    context = dict(CONTEXT, economic_releases=rows)
    source = ("지표 | 발표치 | 예상 | 이전 | 해석 | 반응\n--- | --- | --- | --- | --- | ---\n"
              "CPI | 1 | - | - | a | a\nNFP | 2 | - | - | b | b\nEXP | 3 | - | - | c | c\nPPI | 4 | - | - | d | d")
    result = "\n".join(_recent_releases({"경제지표": source}, context, NOW))
    assert result.index("EXP") < result.index("CPI")  # Newest publication first.
    assert "NFP" not in result and "PPI" not in result  # Undated and future rows stay out.


def test_macro_rows_are_grouped_by_ticker_without_changing_cells():
    rows = ["10Y 금리(^TNX) | 5.15 % | +2.20% · 1개월 변화 | 2026-11-13 | fixture",
            "환율(USDKRW=X) | 1,470.00 원/USD | +0.10% · 1개월 변화 | 2026-11-13 | fixture",
            "유가(CL=F) | 60.00 USD/배럴 | -1.00% · 1개월 변화 | 2026-11-13 | fixture",
            "금 선물(GC=F) | 4,000.00 USD/트로이온스 | +0.50% · 전 거래일 대비 | 2026-11-13 | fixture",
            "VIX(^VIX) | 20.00 pt | +3.00% · 1개월 변화 | 2026-11-13 | fixture",
            "신규지표(ZZZ) | 1.00 pt | 미연결 | 2026-11-13 | fixture"]
    report = REPORT.replace("10Y 금리(^TNX) | 5.15 % | +2.20% · 1개월 변화 | 2026-11-13 | fixture", "\n".join(rows))
    sections = dict(split_report_sections(compose_reading_report(report, context=deepcopy(CONTEXT), news=(), summary_rows=[], now=NOW)))
    macro = sections["매크로"]
    order = [macro.index(f"**{title}**") for title in ("금리", "환율·달러", "원자재", "심리·변동성", "기타")]
    assert order == sorted(order)
    for row in rows:  # Every cell is copied as-is, exactly once.
        assert macro.count(row) == 1
    assert macro.index("유가(CL=F)") < macro.index("**심리·변동성**")
    assert macro.index("신규지표(ZZZ)") > macro.index("**기타**")


def test_observatory_values_are_copied_and_only_collected_items_count_as_shown():
    context = deepcopy(CONTEXT)
    context["observatory_daily"] = {
        "EWZ": {"price": 30.5, "date": "2026-11-13", "previous_price": 30.0, "previous_date": "2026-11-12",
                "return": 30.5 / 30.0 - 1, "source": "Yahoo Finance daily"},
        "INDA": {}, "VNM": {}, "EWJ": {},
        "^VVIX": {"price": 101.25, "date": "2026-11-13", "previous_price": None, "previous_date": "",
                  "return": None, "source": "Yahoo Finance daily"}, "^SKEW": {}, "^OVX": {}}
    sections = dict(split_report_sections(render(context)))
    world, macro, status = sections["세계 시장과 국가 ETF"], sections["매크로"], sections["관측실 지표 연결 상태"]
    assert "브라질 ETF(EWZ) | 30.50 USD | +1.67% · 완료 일봉 · 이전 관측 대비 | 2026-11-12 → 2026-11-13 | Yahoo Finance daily" in world
    assert "인도 ETF(INDA) | 미연결 | 미연결 | 미연결 | 미연결" in world
    assert "브라질 ETF(EWZ) · 본문 표시" in world and "인도 ETF(INDA) · 미연결" in world
    assert "VVIX(^VVIX) | 101.25 pt" in macro and "SKEW(^SKEW) | 미연결" in macro
    assert "VVIX(^VVIX) · 본문 표시" in status and "SKEW(^SKEW) · 미연결" in status
    assert macro.index("**옵션 위험 · 관측실 지표**") > macro.index("10Y 금리(^TNX)")


def test_no_observatory_data_keeps_status_only():
    sections = dict(split_report_sections(render()))
    assert "옵션 위험" not in sections["매크로"]
    assert "브라질 ETF(EWZ) · 미연결" in sections["세계 시장과 국가 ETF"]


def test_observatory_coverage_distinguishes_actual_body_and_appendix_values():
    from stock_lab_core.report_reading import _observatory_status_lines

    body = ("대상 | 수준 | 기준일\n--- | --- | ---\n"
            "VIX(^VIX) | 26.8 pt | 2026-11-25\n"
            "SKEW(^SKEW) | 미연결 | -\n"
            "삼성전자(005930.KS) | 미수집 | -\n"
            "\n본문에 BTC-USD(BTC-USD)가 언급되어도 관측값은 아니다.\n")
    evidence = ("지표 | 관측 | 기준일\n--- | --- | ---\n"
                "하이일드 신용 스프레드 | 3.72% · 전 관측 대비 +9.0bp | 2026-11-24\n"
                "미국 실업률 2026-10 수준 | 4.1% | 2026-10\n"
                "공포·탐욕(FNG) | 미연결 | -\n")
    out = "\n".join(_observatory_status_lines(body, country=False, evidence=evidence))
    assert "VIX(VIXCLS) · 본문 표시" in out
    assert "하이일드 OAS(BAMLH0A0HYM2) · 상세 근거 표시" in out
    assert "미국 실업률(UNRATE) · 상세 근거 표시" in out
    for label in ("SKEW(^SKEW)", "삼성전자(005930.KS)", "비트코인(BTC-USD)", "공포·탐욕(FNG)"):
        assert label + " · 미연결" in out
    moved = "\n".join(_observatory_status_lines(body + "\n" + evidence, country=False, evidence=evidence))
    assert "하이일드 OAS(BAMLH0A0HYM2) · 본문 표시" in moved


def test_observatory_missing_or_nonfinite_cells_are_not_success_and_zero_is_valid():
    from stock_lab_core.report_reading import _observatory_value_symbols

    for value in ("미연결", "미제공", "—", "-", "NaN", "inf", "-inf", "None", "1e999", ""):
        assert not _observatory_value_symbols("대상 | 값\n--- | ---\n공포·탐욕(FNG) | " + value)
    assert _observatory_value_symbols("대상 | 값\n--- | ---\n공포·탐욕(FNG) | 0 점") == {"FNG"}


def test_kr_flow_history_keeps_completed_period_and_excludes_today_provisional():
    from stock_lab_core.report_reading import _kr_flow_table_lines
    flow = ["시장 | 개인 | 외국인 | 기관 | 기준일", "--- | --- | --- | --- | ---",
            "KOSPI | -11,311.28 | +6,851.39 | +2,765.50 | 2026-11-24", "",
            "시장 | 투자자 | 연속 순매수·순매도 | 5거래일 누적 | 20거래일 누적 | 기준일",
            "--- | --- | --- | --- | --- | ---",
            "KOSPI | 외국인 | 순매도 7거래일 | -35,196.49 | -149,375.13 | 2026-11-23",
            "KOSPI | 개인 | 순매도 1거래일 | +9,429.54 | +10,974.89 | 2026-11-23", ""]
    out = "\n".join(_kr_flow_table_lines(flow))
    assert "시장 · 억원(잠정) | 개인" in out and "시장 · 억원(완료 거래일) | 투자자" in out
    assert "기준일(2026-11-23) 마감까지의 완료 거래일 기준" in out
    assert "위 2026-11-24 잠정 수급은 포함하지 않습니다" in out
    assert "KOSPI | 개인 | 순매도 1거래일 | +9,429.54 | +10,974.89 | 2026-11-23" in out


def test_snapshot_flow_history_is_not_called_completed():
    from stock_lab_core.report_reading import _kr_flow_table_lines
    flow = ["시장 | 투자자 | 연속 순매수·순매도 | 5거래일 합계 | 20거래일 합계 | 기준일",
            "--- | --- | --- | --- | --- | ---", "KOSPI | 외국인 | 순매수 2거래일 | +1.00 | +2.00 | 2026-11-24", ""]
    out = "\n".join(_kr_flow_table_lines(flow))
    assert "완료 거래일" not in out and "장중 수치가 포함될 수 있습니다" in out


def test_shared_news_keeps_ten_body_first_rows_and_moves_the_rest_to_audit():
    from stock_lab_core.report_reading import _cap_news_table, _table
    rows = [(f"분야{i}", f"[기사{i}](https://example.test/{i})" + (" · 본문: 사실" if i in (11, 12) else " (제목 확인·기사 주장)"),
             f"11/27 {i:02d}:00", "확인") for i in range(14)]
    main, rest = _cap_news_table(_table(["분야", "확인된 재료", "보도시각·범위", "다음 확인"], rows))
    shown = [r for r in main if r.startswith("분야") and not r.startswith("분야 |")]
    assert len(shown) == 10 and any("기사11]" in r for r in shown) and any("기사12]" in r for r in shown)
    assert [r.split(" | ")[0] for r in shown] == sorted((r.split(" | ")[0] for r in shown), key=lambda x: int(x[2:]))
    assert sum(r.startswith("분야") and not r.startswith("분야 |") for r in rest) == 4 and rest[0] == "### 주요 기업과 사건 · 나머지"
    assert "나머지 4건" in "\n".join(main)
    short = _table(["분야", "확인된 재료", "보도시각·범위", "다음 확인"], rows[:3])
    assert _cap_news_table(short) == (short, [])


def test_quick_holdings_say_uncomputed_instead_of_disappearing():
    from stock_lab_core.report_reading import _quick_holding_lines
    from stock_lab_core.report_input_status import MISSING_ACCOUNT
    assert "오늘 점검 미계산" in _quick_holding_lines(["## 내 보유 종목 영향", MISSING_ACCOUNT])[0]
    assert _quick_holding_lines(["## 다른 표"]) == []
