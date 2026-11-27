"""Precision page panel for the tech review (display only).

B-4 (2026-11-24) shadow, C-5 v2 (2026-11-25, user decision): clusters, strict overhead supply, type-aware reading,
leveraged products shown under their own policy. Nothing here is written back into the decision, the gate, sizing
or the monthly multiplier.
"""

from __future__ import annotations

import pandas as pd

from stock_lab_core.decision_behavior_groups import behavior_group_label
from stock_lab_core.leverage_stage import resolve_leverage_stage
from stock_lab_core.tech_review import build_tech_review_v2, tech_review_v2_record

_KIND_TEXT = {"+": "지지", "-": "부담", "!": "훼손", "?": "미확인", "·": "참고"}


def _yes_no(value, yes="위", no="아래"):
    return "미확인" if value is None else (yes if value else no)


def leverage_policy_rows(decision, workflow, lev) -> list[dict]:
    """L3 / leverage-only policy inputs (existing values only; missing stays 미확인)."""
    d = decision if isinstance(decision, dict) else {}
    wf = workflow if isinstance(workflow, dict) else {}
    read = d.get("leveraged_l3") if isinstance(d.get("leveraged_l3"), dict) else {}
    cyc = read.get("cycle") or {}
    bar = read.get("last_bar") or {}
    record = read.get("record") or {}
    try:
        from stock_lab_core.leverage_l3_policy import MAX_TRANCHES, MIN_BARS_BETWEEN
    except Exception:  # pragma: no cover
        MAX_TRANCHES, MIN_BARS_BETWEEN = 3, 20
    used = int(cyc.get("tranches_used", 0) or 0) if cyc else None
    gap = read.get("bars_since_last_tranche")
    budget = record.get("budget_krw")
    invested = cyc.get("invested")
    try:
        left_budget = f"{float(budget) - float(invested or 0):,.0f}원" if budget is not None else "미설정"
    except (TypeError, ValueError):
        left_budget = "미확인"
    recovery = bar.get("recovery_passed")
    obs = d.get("leveraged_l3_observation") if isinstance(d.get("leveraged_l3_observation"), dict) else {}
    if not read and obs:
        return [{"항목": k, "값": v} for k, v in _observation_rows(obs, wf, lev)]
    note = str(read.get("record_note") or "") if read else ""
    if read and note and budget is None:
        left_budget = f"조회 실패 · {note}"
    rows = [
        ("적용 정책", "레버리지 전용 정책(L0~L3) · 일반 기술검토 종합상태는 평가하지 않음"),
        ("레버리지 단계", f"{lev['stage']} {lev['stage_label']}" if lev else "미확인"),
        ("시장방어", str(wf.get("시장실행상태") or "미확인")),
        ("기초지수 MA50", _yes_no(bar.get("underlying_above_ma50"))),
        ("레버리지 ETF MA50", _yes_no(bar.get("leveraged_above_ma50"))),
        ("회복체크", "미확인" if recovery is None else f"{int(recovery)}/6"),
        ("패닉 latch", "미확인" if not read else (f"유지 ({cyc.get('latch_date')} 발동)" if cyc.get("panic_latched")
                                                 else (f"해제 ({cyc.get('unlatch_date')})" if cyc.get("unlatch_date") else "없음"))),
        ("남은 회차", "미확인" if used is None or not read else f"{max(MAX_TRANCHES - used, 0)}/{MAX_TRANCHES}"),
        (f"{MIN_BARS_BETWEEN}거래일 cooldown", "실행 기록 없음" if read and gap is None else
         ("미확인" if gap is None else (f"마지막 실행 후 {gap}거래일" + (" (충족)" if gap >= MIN_BARS_BETWEEN else " (미충족)")))),
        ("남은 예산", left_budget if read else "미확인"),
        ("L3 판독", str(read.get("status") or "미확인")),
        ("최종 실행가능 여부", str(wf.get("게이트상태") or "미확인")),
    ]
    return [{"항목": k, "값": v} for k, v in rows]


def _observation_rows(obs, wf, lev):
    """L0 (not held): price-only inputs are observed; cycle rules are 해당 없음, never 미확인 or 0."""
    na = "해당 없음 · " + str(obs.get("reason") or "L0 미보유")
    under = obs.get("underlying_above_ma50")
    under_text = (f"조회 실패 · {obs.get('underlying_error')}" if under is None and obs.get("underlying_error")
                  else _yes_no(under) + (f" ({obs.get('axis')} {obs.get('underlying_date')} 종가)" if under is not None else ""))
    rec, total = obs.get("recovery_passed"), obs.get("recovery_total") or 6
    return [
        ("적용 정책", "레버리지 전용 정책(L0~L3) · 일반 기술검토 종합상태는 평가하지 않음"),
        ("레버리지 단계", f"{lev['stage']} {lev['stage_label']}" if lev else "미확인"),
        ("시장방어", str(wf.get("시장실행상태") or "미확인")),
        ("기초지수 MA50", under_text),
        ("레버리지 ETF MA50", _yes_no(obs.get("leveraged_above_ma50"))),
        ("회복체크", "미확인" if rec is None else f"{int(rec)}/{int(total)}"),
        ("패닉 latch", na),
        ("남은 회차", na),
        ("20거래일 cooldown", na),
        ("남은 예산", na),
        ("L3 판독", na),
        ("최종 실행가능 여부", str(wf.get("게이트상태") or "미확인")),
    ]


def tech_review_rows(decision, workflow, *, pattern_candidates=None, liquidity_profile=None, invalidated_patterns=None,
                     has_pos=False, is_etf=False, monthly_signal_decision=None, multiplier_fn=None) -> dict:
    """Build the panel model without touching ``decision`` (a copy is never written back)."""
    d = decision if isinstance(decision, dict) else {}
    wf = workflow if isinstance(workflow, dict) else {}
    mult = None
    if isinstance(monthly_signal_decision, dict) and callable(multiplier_fn):
        try:
            mult = multiplier_fn(monthly_signal_decision, "leverage", 0)
        except Exception:
            mult = None
    lev = resolve_leverage_stage(d, gate_state=wf.get("게이트상태"), market_state=wf.get("시장실행상태"),
                                 monthly_multiplier=mult)
    is_leveraged = bool(lev) or bool(d.get("is_leveraged_or_inverse"))
    review = build_tech_review_v2(d, pattern_candidates=pattern_candidates, liquidity_profile=liquidity_profile,
                                  invalidated_patterns=invalidated_patterns, has_pos=has_pos, is_etf=is_etf,
                                  is_leveraged=is_leveraged)
    summary = [
        {"항목": "기존 판정", "값": str(d.get("dec", "-") or "-")},
        {"항목": "판정코드 · 행동그룹", "값": f"{d.get('decision_code', '-') or '-'} · {behavior_group_label(d.get('decision_code'))}"},
        {"항목": "판정분류 · 실행게이트", "값": f"{wf.get('판정분류', '-') or '-'} · {wf.get('게이트상태', '-') or '-'}"},
        {"항목": "판정 유형", "값": review["strategy_type"]},
        {"항목": "기술검토(v2)", "값": f"{review['verdict']} · {review['label']}"},
        {"항목": "정책 버전", "값": review["policy_version"]},
    ]
    if lev:
        mult_text = "미확인(월간 신호 캐시 없음)" if lev["monthly_multiplier"] is None else f"×{lev['monthly_multiplier']:g}"
        summary.append({"항목": "레버리지 단계", "값": f"{lev['stage']} {lev['stage_label']} · 월간 배율 {mult_text}"
                        + (" · 계획금액≠실행게이트" if lev["plan_gate_mismatch"] else "")})
    reasons = [{"구분": area, "방향": _KIND_TEXT.get(kind, kind), "근거": text} for kind, area, text in review["reasons"]]
    return {"review": review, "leverage": lev, "summary": summary, "reasons": reasons,
            "clusters": review["clusters"], "record": tech_review_v2_record(review),
            "leverage_rows": leverage_policy_rows(d, wf, lev) if is_leveraged else []}


def render_tech_review_shadow(st, decision, workflow, **kwargs) -> dict:
    model = tech_review_rows(decision, workflow, **kwargs)
    review = model["review"]
    with st.expander(f"🔬 기술검토(v2, 표시 전용) · {review['verdict']} {review['label']}", expanded=False):
        st.caption(review["note"] + " · 관찰용 임계값(기존 값 재사용, 새 임계값 없음)")
        st.dataframe(pd.DataFrame(model["summary"]), width="stretch", hide_index=True)
        if model["leverage_rows"]:
            st.markdown("**레버리지 전용 정책 적용**")
            st.dataframe(pd.DataFrame(model["leverage_rows"]), width="stretch", hide_index=True)
            st.caption("회복체크는 신규진입 계획의 '회복 n/6'과 같은 6항목(MA20·MA50·MA120·MACD·RS 기울기·기초축 1W)입니다. "
                       "미보유(L0)는 회차·예산 규칙이 '해당 없음'이고, 조회 실패만 '조회 실패'로 표시합니다.")
            st.caption("아래 일반 기술검토 근거는 참고용이며 L3 판정·사이징에 영향을 주지 않습니다.")
        if review.get("type_note"):
            st.caption(review["type_note"])
        if model["clusters"]:
            st.caption("같은 가격 움직임에서 나온 근거는 묶음 하나로 셉니다. 개별 근거는 아래 표에 그대로 남깁니다.")
            st.dataframe(pd.DataFrame(model["clusters"]), width="stretch", hide_index=True)
        if model["reasons"]:
            st.dataframe(pd.DataFrame(model["reasons"]), width="stretch", hide_index=True)
        else:
            st.caption("근거로 잡힌 항목이 없습니다.")
        st.caption("추정 매물대는 일봉 거래량을 가격대에 나눈 추정치이며 실제 호가가 아닙니다. " + review["block_note"])
    return model


from stock_lab_core.report_build import register_loaded_source  # noqa: E402

register_loaded_source(__name__, __file__)
