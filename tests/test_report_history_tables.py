from copy import deepcopy

from stock_lab_core.report_comparison import history_comparison_lines


def row(ticker, reason="개별 위험사유 없음", *, gate="방어우선", name="", held=False):
    return {"티커": ticker, "종목명": name or ticker, "보유여부": held,
            "최종읽기": "데이터확인: 판단 보류" if gate == "데이터확인" else "방어우선: 추가매수 보류",
            "게이트상태": gate, "저장사유": [reason]}


def test_distinct_baseline_counts_and_identical_transitions_are_deduplicated():
    held = [row(f"H{i}", held=True) for i in range(10)]
    watch = [row(f"W{i}") for i in range(75)]
    current = held + watch
    current[10] = row("W0", "가격급락", name="Datadog")
    current[11] = row("W1", gate="데이터확인", name="원익홀딩스")
    previous = deepcopy(current[:77])
    previous[10] = row("W0", name="Datadog")
    previous[11] = row("W1", name="원익홀딩스")
    for index in range(12, 17):
        previous[index]["저장사유"] = ["가격급락"]
    same = deepcopy(current[:83])
    same[10] = row("W0", name="Datadog")
    same[11] = row("W1", name="원익홀딩스")
    for index in range(12, 14):
        same[index]["저장사유"] = ["추세훼손"]
    baselines = [dict(previous=previous, previous_date="2026-10-16/2026-10-19", current_date="2026-10-19/2026-10-20"),
                 dict(previous=same, previous_date="2026-10-19/2026-10-20", current_date="2026-10-19/2026-10-20",
                      same_session=True, previous_run_at="2026-10-20T14:48:32.695410+00:00")]
    original = deepcopy((current, baselines))
    lines = history_comparison_lines(current, baselines)
    output = "\n".join(lines)
    assert "관심·미보유 75개 | 67 | 8 | 7개" in output
    assert "관심·미보유 75개 | 73 | 2 | 4개" in output
    assert output.count("보유 10개 | 10 | 0 | 0개") == 2
    assert "2026-10-20 23:48 KST" in output and "+00:00" not in output
    ddog = [line for line in lines if line.startswith("Datadog(W0) |")]
    assert len(ddog) == 1 and ddog[0].endswith("이전 거래일 · 같은 거래일 직전 생성")
    wonik = [line for line in lines if line.startswith("원익홀딩스(W1) |")]
    assert len(wonik) == 1 and "판정·게이트" in wonik[0]
    assert output.count("W74(종목명 미저장)") == 1
    assert (current, baselines) == original


def test_same_symbol_different_transitions_are_never_collapsed():
    current = [row("TEST", "개별 위험사유 없음")]
    baselines = [dict(previous=[row("TEST", "가격급락")], previous_date="2026-10-19", current_date="2026-10-20"),
                 dict(previous=[row("TEST", "추세훼손")], previous_date="2026-10-20", current_date="2026-10-20", same_session=True)]
    lines = history_comparison_lines(current, baselines)
    assert len([line for line in lines if line.startswith("TEST(종목명 미저장) | 사유")]) == 2


def test_uncomparable_and_membership_changes_do_not_look_unchanged():
    result = "\n".join(history_comparison_lines([row("NEW", name="신규 | 이름")], [
        dict(previous=[row("OLD")], previous_date="2026-10-19", current_date="2026-10-20")]))
    assert "비교 불가" in result and "변경 없음" not in result
    assert "추가 | 신규 / 이름(NEW)" in result and "이탈 | OLD(종목명 미저장)" in result
    assert "삭제 여부는 미확인" in result


def test_history_keeps_more_than_ten_changes_and_escapes_every_table_cell():
    current = [row(str(i), "가격급락") for i in range(25)]
    prior = [row(str(i)) for i in range(25)]
    lines = history_comparison_lines(current, [dict(previous=prior, previous_date="2026-10-19", current_date="2026-10-20")])
    assert sum(" | 사유 | " in line for line in lines) == 25
