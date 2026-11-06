from copy import deepcopy
from datetime import datetime

from stock_lab_core.report_account import cumulative_account_table
from stock_lab_core.report_policy_catalysts import election_context_lines
from stock_lab_core.safeguard_history import merge_safeguard_history

NOW = datetime.fromisoformat("2026-11-06T09:43:00+09:00")


def test_audience_ratings_are_not_election_results():
    row = dict(title="美중간선거 개표방송 1위는 NBC 시청률 상승", market="US",
               session_date="2026-11-05", published_at="2026-11-06T08:00:00+09:00",
               link="https://www.yna.co.kr/view/EXAMPLE", publisher="연합뉴스")
    output = "\n".join(election_context_lines({}, [row], [], NOW))
    assert "NBC" not in output
    assert "개표 진행·의석 결과 미연결" in output


def event(direction, suffix):
    return dict(date="2026-11-06", market="KOSPI", kind="circuit_breaker", direction=direction,
                status="reported", source="Example", source_url="https://example.com/" + suffix)


def test_unknown_breaker_direction_merges_preserving_sources_without_mutation():
    rows = [event("unknown", "a"), event("down", "b")]
    before = deepcopy(rows)
    result = merge_safeguard_history(rows, [], ["2026-11-06"], NOW)
    assert len(result) == 1 and result[0]["direction"] == "down"
    assert len(result[0]["sources"]) == 2
    assert rows == before


def test_ambiguous_sidecar_directions_are_not_collapsed():
    rows = [dict(event(direction, direction), kind="sidecar") for direction in ("unknown", "buy", "sell")]
    assert len(merge_safeguard_history(rows, [], ["2026-11-06"], NOW)) == 3


def test_weight_basis_is_not_presented_as_reconstructed_start_weight():
    metrics = {"total": -2., "coverage": 99., "groups": {}, "missing": []}
    before = deepcopy(metrics)
    lines = "\n".join(cumulative_account_table(metrics))
    assert "기간 시작 비중 아님" in lines and "시작 총자산 분모" in lines
    assert metrics == before
