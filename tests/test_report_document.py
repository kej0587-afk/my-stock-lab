"""Final-output contracts, not a byte-for-byte guarantee of duplicated output."""

from copy import deepcopy

from stock_lab_core.report_document import additional_evidence, decision_summary_lines
from stock_lab_core.report_view import _report_lines, split_report_sections
from tests.test_report_reading import CONTEXT, NOW, REPORT
from stock_lab_core.report_reading import AUDIT_TITLE, compose_reading_report


GUARD = """## 시장방어 게이트 근거
현재 국장 방어 · 미장 주의 · 통합 위험

**기준일 지연 · 미국**: 게이트 2026-11-12 / 리포트 정규장 종가 2026-11-13. 재계산 필요.

**핵심 요약** · 통합 10점 = 지역 최대 7 + 흐름 3 · 위험 구간 이탈: 8 미만, 최소 3점 감소

**다음 경계** · 확산 16.3%·+2점 → 35% 이상(+18.7%p) / 전술 미충족

구성 요소 | 현재값 | 기존 기준 | 기준까지 남은 조건
--- | --- | --- | ---
통합 시장 점수 | 10 | 8 이상 위험 | 8 미만
"""


def test_existing_decision_and_conditions_precede_data_without_changing_inputs():
    context = deepcopy(CONTEXT)
    context["market_guard"] = {"action": "신규매수 중단 · 현금/리스크 점검"}
    rows = [{"데이터상태": "입력 변경 · 이전 계산 결과 · 재계산 필요 · OK",
             "게이트근거": "입력 변경 · 이전 계산 결과 · 재계산 필요"}]
    before = deepcopy((context, rows))
    report = REPORT + "\n" + GUARD
    output = compose_reading_report(report, context=context, news=[], summary_rows=rows, now=NOW)
    # Market first: the first screen keeps the existing action and stale-input warnings,
    # while the full judgment and boundaries move to the account area unchanged.
    top = output.split("## 지수", 1)[0]
    assert "**기존 실행 방향** · 신규매수 중단 · 현금/리스크 점검" in top
    for value in ("기준일 지연 · 미국", "입력 변경 · 이전 계산 결과 · 재계산 필요"):
        assert value in top
    judgment = dict(split_report_sections(output))["오늘의 판단"]
    for value in ("**기존 실행 방향** · 신규매수 중단 · 현금/리스크 점검", "10점 = 지역 최대 7 + 흐름 3",
                  "35% 이상(+18.7%p)", "기준일 지연 · 미국",
                  "입력 변경 · 이전 계산 결과 · 재계산 필요", "보유 전량 매도 지시가 아닙니다"):
        assert value in judgment
    assert output.count("**핵심 요약**") == output.count("**다음 경계**") == 1
    assert "통합 시장 점수 | 10 | 8 이상 위험 | 8 미만" in output.split("## " + AUDIT_TITLE)[1]
    assert (context, rows) == before
    assert len([line for _, line in _report_lines(output) if line.startswith("# ")]) == 1


def test_missing_account_is_not_zero_or_buy_permission():
    from stock_lab_core.report_input_status import report_scope_lines
    source = "# Fixture\n\n" + "\n".join(report_scope_lines([]))
    result = "\n".join(decision_summary_lines(dict(split_report_sections(source)), context={}, summary_rows=[]))
    assert "시장 전용" in result and "계좌 입력 미연결" in result
    assert "0개" not in result and "시장 게이트 입력 미연결" in result
    assert "재검토 조건 미연결" in result


def test_top_uses_existing_interpretation_without_repeating_market_overview():
    from stock_lab_core.report_market_summary import market_summary
    from stock_lab_core.report_session import market_session_states
    from tests.test_report_market_summary import case, NOW as summary_now

    context, news = case()
    before = deepcopy((context, news))
    synthesis = market_summary(context, news, [], market_session_states(summary_now, context["sessions"]), summary_now)
    interpretation = synthesis["interpretation"]
    assert interpretation and interpretation in synthesis["headline"]
    assert len(interpretation) < 200
    output = compose_reading_report(REPORT, context=context, news=news, summary_rows=[], now=summary_now)
    top = output.split("## 지금 상태 3줄", 1)[0].split("## 이번 주 테마", 1)[0]
    assert "**시장 해석** · " + interpretation in top
    assert synthesis["overview"] not in top
    assert (context, news) == before


def test_row_dedup_only_within_explicit_source_destination_preserves_different_date():
    table = "대상 | 값 | 기준일\n--- | --- | ---\nA | 1% | 2026-11-13\nB | 2% | 2026-11-13"
    source = "# Fixture\n\n## 지수·매크로 한눈에\n" + table + "\nA | 1% | 2026-11-12"
    source += "\n\n## 다른 맥락\n" + table
    reader = "# Fixture\n\n## 지수\n" + table.split("\nB |")[0]
    reader += "\n\n## 매크로\n대상 | 값 | 기준일\n--- | --- | ---\nB | 2% | 2026-11-13"
    remaining = dict(split_report_sections(additional_evidence(source, reader)))
    assert "2026-11-12" in remaining["지수·매크로 한눈에"]
    assert "2026-11-13" not in remaining["지수·매크로 한눈에"]
    assert table in remaining["다른 맥락"]


def test_one_title_with_bom_and_fenced_headings_are_evidence_not_report_boundaries():
    source = "\ufeff" + REPORT + "\n## 원문 예시\n```md\n# quoted title\n\n## quoted section\n```\n"
    output = compose_reading_report(source, context=CONTEXT, news=[], summary_rows=[], now=NOW)
    assert "```md\n# quoted title\n\n## quoted section\n```" in output
    assert len([line for _, line in _report_lines(output) if line.startswith("# ")]) == 1


def test_every_original_table_row_survives_once_unless_projection_has_extra_fields():
    from stock_lab_core.report_reading import tables
    output = compose_reading_report(REPORT, context=CONTEXT, news=[], summary_rows=[], now=NOW)
    for _, rows in tables(REPORT):
        for row in rows:
            assert all(cell in output for cell in row), row
    main, audit = output.split("## " + AUDIT_TITLE, 1)
    assert "PPI 근거 · 2026-11-13 원문" not in main
    assert "PPI 근거 · 2026-11-13 원문" in audit
