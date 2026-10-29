"""Compact history presentation; no storage, fetching, or investment decisions.

build_history_change_view is pure. render_history_changes accepts an injected
Streamlit surface and the same single-baseline arguments as comparison_lines.
For report history, pass its existing baseline dictionaries via baselines=.
Date/ticker identity, comparison eligibility, reason normalization, and counts
follow report_comparison. Full legacy output is retained as collapsed Markdown.
"""

import pandas as pd

from stock_lab_core.report_comparison import (
    _date_pair, _dates, _label, _reasons, history_comparison_lines,
)
from stock_lab_core.report_evidence import KST, first, is_held, records, stamp, text


def _ticker(row):
    return text(first(row, "티커", "ticker"))


def _verdict(row):
    return text(first(row, "최종읽기", "🔥기술적 타점", "판정코드"))


def _fields(prior, row):
    before, after = _verdict(prior), _verdict(row)
    old_gate, new_gate = (text(first(item, "게이트상태", "gate_state")) for item in (prior, row))
    gate_in_verdict = bool(old_gate and new_gate and before.startswith(old_gate) and after.startswith(new_gate))
    fields = []
    if before != after:
        fields.append(("판정·게이트" if old_gate != new_gate and gate_in_verdict else "판정", before, after))
    if old_gate != new_gate and not (before != after and gate_in_verdict):
        fields.append(("게이트", old_gate or "미제공", new_gate or "미제공"))
    old_reasons, new_reasons = _reasons(prior), _reasons(row)
    if old_reasons != new_reasons:
        fields.append(("사유", ", ".join(old_reasons), ", ".join(new_reasons)))
    return fields


def build_history_change_view(current, baselines):
    """Keep baseline-specific counts and merge only identical full transitions.

    Missing verdicts remain uncomparable, not unchanged. Membership differences
    are input-list changes, never purchases, sales, or confirmed deregistration.
    A reason-only change retains its unchanged verdict and full reason delta.
    """
    current_rows = records(current)
    baselines = list(baselines)
    current_map = {_ticker(row): row for row in current_rows if _ticker(row)}
    summary, changes, membership = [], {}, {}
    for baseline in baselines:
        previous_date, current_date = text(baseline.get("previous_date")), text(baseline.get("current_date"))
        previous_dates, current_dates = _dates(previous_date), _dates(current_date)
        same = baseline.get("same_session", False)
        comparable = bool(previous_dates) and len(previous_dates) == len(current_dates)
        valid = comparable and (previous_dates == current_dates if same else
                                all(old <= new for old, new in zip(previous_dates, current_dates)) and
                                any(old < new for old, new in zip(previous_dates, current_dates)))
        if not valid:
            continue
        reference = "같은 거래일 직전 생성" if same else "이전 저장 기준일"
        at = stamp(baseline.get("previous_run_at")) if same else None
        basis = at.astimezone(KST).strftime("%Y-%m-%d %H:%M KST") if at else _date_pair(previous_date)
        old = {_ticker(row): row for row in records(baseline.get("previous")) if _ticker(row)}
        compared, changed = {True: 0, False: 0}, {True: 0, False: 0}
        for ticker, row in current_map.items():
            prior = old.get(ticker)
            if prior is None or not _verdict(prior) or not _verdict(row):
                continue
            held = is_held(row)
            compared[held] += 1
            fields = _fields(prior, row)
            if not fields:
                continue
            changed[held] += 1
            key = (ticker, held, _verdict(prior), _verdict(row), tuple(fields))
            item = changes.setdefault(key, {
                "ticker": ticker, "name": _label(row, prior), "held": held,
                "before": _verdict(prior), "after": _verdict(row), "fields": fields,
                "reasons": list(_reasons(row)), "references": [], "kind": "change",
            })
            if reference not in item["references"]:
                item["references"].append(reference)
        for held in (True, False):
            total = sum(is_held(row) == held for row in current_rows)
            summary.append({"reference": reference, "basis": basis, "held": held, "total": total,
                            "compared": compared[held], "uncompared": total - compared[held],
                            "changed": changed[held] if compared[held] else None})
        for action, tickers, source in (("추가", sorted(current_map.keys() - old.keys()), current_map),
                                        ("이탈", sorted(old.keys() - current_map.keys()), old)):
            for ticker in tickers:
                row = source[ticker]
                item = membership.setdefault((action, ticker), {
                    "ticker": ticker, "name": _label(row), "held": is_held(row), "action": action,
                    "origin": text(row.get("입력출처")) or "미확인", "references": [], "kind": "membership",
                })
                if reference not in item["references"]:
                    item["references"].append(reference)
    order = lambda item: (not item["held"], item["name"], item["ticker"])
    return {
        "summary": summary, "changes": sorted(changes.values(), key=order),
        "membership": sorted(membership.values(), key=order),
        "full_lines": history_comparison_lines(current_rows, baselines),
    }


def _short(value, limit):
    value = " ".join(text(value).split())
    return value if len(value) <= limit else value[:limit - 1] + "…"


def _compact_row(item):
    if item["kind"] == "membership":
        transition = "목록 없음 → 추가" if item["action"] == "추가" else "목록 포함 → 이탈"
        reason = item["origin"] + " 입력 목록 차이"
    else:
        transition = item["before"] + " → " + item["after"]
        gate = next((field for field in item["fields"] if field[0] == "게이트"), None)
        if item["before"] == item["after"]:
            transition = "게이트 " + gate[1] + " → " + gate[2] if gate else "판정 유지: " + item["after"]
        delta = next((field for field in item["fields"] if field[0] == "사유"), None)
        reason = delta[1] + " → " + delta[2] if delta else ", ".join(item["reasons"]) or "사유 미제공"
        if gate and item["before"] != item["after"]:
            reason = "게이트 " + gate[1] + " → " + gate[2] + " · " + reason
        if len(item["references"]) > 1:
            reason += " · 두 기준 공통"
    return {"종목": _short(item["name"], 42), "이전 → 현재": _short(transition, 70),
            "주요 사유": _short(reason, 80)}


def _table(st, rows):
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", row_height=64,
                     height=min(420, 38 + len(rows) * 64))


def render_history_changes(st, current, previous=None, *, previous_date="", current_date="",
                           same_session=False, previous_run_at="", baselines=None, holding_limit=6):
    """Holdings first, explicit counts, three short columns, remaining rows closed.

    No imports of app.py, Streamlit globals, stores, or decision engines. The
    caller remains responsible for selecting its existing account-bound history.
    Returns the pure view for callers/tests, without modifying either snapshot.
    """
    if isinstance(holding_limit, bool) or not isinstance(holding_limit, int) or holding_limit < 1:
        raise ValueError("holding_limit must be a positive integer")
    if baselines is None:
        baselines = [{"previous": previous, "previous_date": previous_date, "current_date": current_date,
                      "same_session": same_session, "previous_run_at": previous_run_at}]
    view = build_history_change_view(current, baselines)
    st.markdown("**판정 이력 변화**")
    if not view["summary"]:
        st.caption("비교 가능한 저장 이력 없음")
    else:
        for start in range(0, len(view["summary"]), 2):
            pair = view["summary"][start:start + 2]
            st.caption(pair[0]["reference"] + " · " + pair[0]["basis"])
            _table(st, [{"대상": "보유" if row["held"] else "관심·미보유",
                        "전체": row["total"], "변경": str(row["changed"]) if row["changed"] is not None else "비교 불가",
                        "비교": row["compared"], "미비교": row["uncompared"]} for row in pair])
        held = [row for row in [*view["changes"], *view["membership"]] if row["held"]]
        st.markdown(f"**보유 변화 · {len(held)}건**")
        _table(st, [_compact_row(row) for row in held[:holding_limit]])
        if not held:
            st.caption("보유 판정·사유 변경 없음" if any(r["held"] and r["compared"] for r in view["summary"])
                       else "비교 가능한 보유 판정 없음")
        if len(held) > holding_limit:
            with st.expander(f"추가 보유 변화 · {len(held) - holding_limit}건", expanded=False):
                _table(st, [_compact_row(row) for row in held[holding_limit:]])
        watch = [row for row in view["changes"] if not row["held"]]
        if watch:
            with st.expander(f"관심·미보유 변화 · {len(watch)}건", expanded=False):
                _table(st, [_compact_row(row) for row in watch])
        if view["membership"]:
            st.markdown("**입력 목록 변화**")
            origins = list(dict.fromkeys(["등록", "자동", "보유목록", "미확인"] +
                                         [row["origin"] for row in view["membership"]]))
            counts = [{"출처": origin, **{action: sum(row["origin"] == origin and row["action"] == action
                       for row in view["membership"]) for action in ("추가", "이탈")}} for origin in origins]
            _table(st, [row for row in counts if row["추가"] or row["이탈"]])
            with st.expander(f"등록·자동 입력 상세 · {len(view['membership'])}건", expanded=False):
                _table(st, [_compact_row(row) for row in view["membership"]])
            st.caption("입력 목록 차이입니다. 매매 내역이나 관심등록 삭제 여부는 미확인입니다.")
    if view["full_lines"]:
        with st.expander("비교 기준·판정·사유 원문", expanded=False):
            st.markdown("\n".join(view["full_lines"]))
    return view
