from datetime import datetime
from zoneinfo import ZoneInfo
from copy import deepcopy
import itertools

from stock_lab_core.report_dashboard import current_state_lines, market_board_lines
from stock_lab_core.report_session import market_session_states
from stock_lab_core.market_guard_explanation import compose_market_guard_score, guard_explanation_lines
from stock_lab_core.report_evidence import curate_news


NOW = datetime(2026, 10, 30, 15, 25, tzinfo=ZoneInfo("Asia/Seoul"))


def context():
    return {"sessions": {"KR": "2026-10-29", "US": "2026-10-29"},
            "prices": {"^KS11": {"date": "2026-10-29", "return": .02, "price": 5000},
                       "^SOX": {"date": "2026-10-29", "return": -.014, "price": 7000},
                       "GC=F": {"date": "2026-10-29", "return": .012, "price": 4000}},
            "intraday_prices": {"^KS11": {"date": "2026-10-30", "as_of": NOW.isoformat(), "return": -.0378,
                                          "price": 4811, "source": "Naver"}},
            "extended_prices": {"SOXX": {"date": "2026-10-30", "previous_date": "2026-10-29",
                                         "as_of": NOW.isoformat(), "return": -.0522}},
            "scenario_observations": {"latest": {"NQ=F": {"return": -.0201, "as_of": NOW.isoformat()}}},
            "macro_data": {"유가": {"val": 102, "chg": 2, "as_of": "2026-10-29", "source": "fixed"}}}


def test_summary_is_three_current_lines_and_does_not_reuse_past_kr_close():
    ctx = context()
    original = deepcopy(ctx)
    lines = current_state_lines(ctx, market_session_states(NOW), NOW, {"total": -4.58, "coverage": 95.2})
    assert len(lines) == 3
    assert len("".join(lines)) < 500
    assert "-3.78%" in lines[0] and "+2.00%" not in lines[0]
    assert "-5.22%" in lines[1] and "-2.01%" in lines[1]
    assert "-4.58%p" in lines[2]
    assert ctx == original


def test_low_coverage_suppresses_account_number():
    lines = current_state_lines(context(), market_session_states(NOW), NOW, {"total": 7.13, "coverage": 33.9})
    assert "7.13" not in lines[2]
    assert "보류" in lines[2] and "33.9%" in lines[2]


def test_data_basis_caption_uses_actual_quote_cache_setting():
    import ast
    from pathlib import Path
    from types import SimpleNamespace
    from stock_lab_core.prices import _LATEST_PRICE_CACHE_TTL_SECONDS
    source = Path(__file__).resolve().parents[1] / "app.py"
    tree = ast.parse(source.read_text(encoding="utf-8-sig"))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "render_data_basis_caption")
    output = []
    ns = {"st": SimpleNamespace(caption=output.append), "format_kst_now": lambda: "테스트 시각",
          "get_market_status_label": lambda ticker: "한국 마감"}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(source), "exec"), ns)
    ns[fn.name]("점검")
    assert f"현재가 기본 캐시 {_LATEST_PRICE_CACHE_TTL_SECONDS}초" in output[0]
    assert "공급 시세 시각은 별도" in output[0]


def test_missing_extended_quote_is_not_presented_as_daymarket():
    ctx = context()
    ctx["extended_prices"] = {}
    ctx["scenario_observations"] = {}
    ctx["prices"]["SOXX"] = {"date": "2026-10-29", "return": .0713}
    lines = current_state_lines(ctx, market_session_states(NOW), NOW, {})
    assert "7.13" not in lines[1]
    assert "미연결" in lines[1]


def test_board_levels_signs_dates_units_and_sox_not_soxx():
    board = "\n".join(market_board_lines(context(), market_session_states(NOW), NOW))
    assert "4,811.00 pt" in board and "-3.78%" in board
    assert "필라델피아 반도체(^SOX)" in board and "7,000.00 pt" in board
    assert "금 선물(GC=F)" in board and "USD/트로이온스" in board
    assert "은 선물(SI=F) | 미연결" in board
    assert "102.00 USD/배럴" in board


def test_guard_extraction_matches_old_rules_exhaustively():
    for regional, flow, macro, event in itertools.product(range(17), range(4), range(4), range(3)):
        old = regional + flow
        if macro >= 2:
            old += macro
        elif macro == 1 and regional < 5:
            old += 1
        if event >= 2:
            old += event
        elif event == 1 and regional < 5:
            old += 1
        if regional >= 5 and macro + event >= 3:
            old += 1
        actual, parts = compose_market_guard_score(regional, flow, macro, event)
        assert actual == old == sum(parts.values())


def test_guard_is_read_only_and_distinguishes_crash_threshold_from_actual_halt():
    guard = {"score": 10, "mode": "위험", "kr_stats": {"score": 8, "circuit_day": 1, "below20": 3},
             "flow_breadth": .3, "flow_accel": .2}
    original = deepcopy(guard)
    out = "\n".join(guard_explanation_lines(guard))
    assert "최소 3점 감소" in out
    assert "실제 서킷 발동과 별개" in out
    assert "20.0%p 회복" in out
    assert guard == original


def test_urgent_news_precedes_workshop_even_if_older():
    rows = [{"title": title, "publisher": "연합뉴스", "link": f"https://www.yna.co.kr/view/{i}",
             "market": "KR", "session_date": "2026-10-30", "published_at": f"2026-10-30T{hour}:00:00+09:00"}
            for i, (title, hour) in enumerate((("거래소 코스피 공시담당자 워크숍 개최", "15"),
                ("코스피 매도 사이드카 발동", "10"), ("코스피 급락...미국 실적 충격", "11"),
                ("일본은행 금리 동결", "12")))]
    selected = curate_news(rows, now=NOW, limit=3)
    assert "사이드카" in selected[0]["title"]
    assert all("워크숍" not in row["title"] for row in selected)
