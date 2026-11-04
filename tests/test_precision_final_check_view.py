"""The final-check caption cannot obscure an already computed account block."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from stock_lab_core.precision_final_check_view import render_final_check_heading


@pytest.mark.parametrize("gate,label,allowed", [
    ("방어우선", "조건부 DCA 대기", False),
    ("방어우선", "매수 금지", False),
    ("대기/관찰", "분할 가능", False),
    ("실행가능", "분할 가능", True),
])
def test_final_header_keeps_raw_result_and_prioritizes_restriction(gate, label, allowed):
    markdowns, metrics = [], []
    ui = SimpleNamespace(
        markdown=lambda value, **kw: markdowns.append(value), caption=lambda value: None,
        columns=lambda n: [SimpleNamespace(metric=lambda *args: metrics.append(args)) for _ in range(n)],
    )
    summary = dict(final_label=label, final_color="#abc", action="원래 개별 점검 해석",
                   execution_allowed=allowed, pass_count=4, caution_count=5,
                   block_count=0 if allowed else 3, core_missing_ids=[])
    workflow = {"게이트상태": gate, "게이트근거": "목표비중/비중초과 우선"}
    original = deepcopy(summary), deepcopy(workflow)
    render_final_check_heading(ui, "RAM", summary, workflow)
    assert metrics[0] == ("최종 판정" if allowed else "개별 점검 판정", label)
    if not allowed:
        assert "현재 실행: 실행 보류" in markdowns[0]
        assert "목표비중/비중초과 우선" in markdowns[0]
        assert "실행 제한 우선" in markdowns[1]
    assert summary["action"] in markdowns[-1]
    assert (summary, workflow) == original
