"""B-5 (2026-11-24): one function that reads the leveraged-ETF stage from a final decision.

The leveraged path is spread over the engine, the Today dashboard override
(``apply_leveraged_dca_dashboard_override``), the precision override
(``apply_leveraged_precision_decision_override``), the execution gate, the market
guard (``attach_market_execution_context``) and the monthly rebalance multiplier.
This module does not decide anything. It reads what those steps already produced and
returns a single stage record, so current results are reproduced by construction and
C-stage work (L3 rules) can be compared against one place.

Stages (current behaviour, nothing new):
- L0: not held, watch only (no DCA amount)
- LX: excluded by target weight (zero target or target filled)
- L1: wait/blocked (overheat pass, before recovery, daily drop no-add, panic zone)
- L2: conditional small tranche (still a gate wait today)
- L3: executable leveraged DCA (C-3, 2026-11-25): LEVERAGED_L3_RECOVERY_DCA, only with a stored cycle budget,
  the user's recorded tranches and this month's monthly plan; ``l3_status`` carries the cycle read.
"""

from __future__ import annotations

import math

LEVERAGE_STAGE_BY_CODE = {
    "LEVERAGED_WATCH_NO_POSITION": ("L0", "미보유 관찰"),
    "LEVERAGED_TARGET_ZERO_DCA_EXCLUDED": ("LX", "목표비중 없음·DCA 제외"),
    "LEVERAGED_TARGET_FILLED_DCA_EXCLUDED": ("LX", "목표비중 충족·DCA 제외"),
    "LEVERAGED_DCA_OVERHEAT_PASS": ("L1", "과열패스·눌림 대기"),
    "LEVERAGED_RECOVERY_DCA_BLOCK": ("L1", "회복 전·DCA 보류"),
    "LEVERAGED_DAILY_DROP_NO_ADD": ("L1", "급락일·추가 금지"),
    "LEVERAGED_DCA_CONDITIONAL": ("L2", "조건부 소액"),
    "LEVERAGED_RECOVERY_DCA_CONDITIONAL": ("L2", "회복 조건부 소액"),
    # C-3 (2026-11-25): executable only with a stored budget, recorded tranches and this month's monthly plan.
    "LEVERAGED_L3_RECOVERY_DCA": ("L3", "회복 확인 · 사전 예산 1/3 회차"),
}
MARKET_DEFENSE_STATES = frozenset({"레버리지 시장방어", "시장방어: 신규매수 중단"})
EXECUTABLE_GATE = "실행가능"


def is_leveraged_decision(decision) -> bool:
    if not isinstance(decision, dict):
        return False
    code = str(decision.get("decision_code", "") or "")
    return bool(decision.get("is_leveraged_or_inverse")) or code.startswith("LEVERAGED_") or bool(
        decision.get("leveraged_dca_stage"))


def resolve_leverage_stage(decision, *, gate_state=None, market_state=None, monthly_multiplier=None) -> dict:
    """Read the current leveraged stage. Returns {} for non-leveraged decisions.

    gate_state / market_state / monthly_multiplier are optional, already computed values.
    A missing value stays None (미확인); it is never filled with 0.
    """
    if not is_leveraged_decision(decision):
        return {}
    code = str(decision.get("decision_code", "") or "")
    stage, label = LEVERAGE_STAGE_BY_CODE.get(code, ("L?", "기존 판정 유지(레버리지 전용 코드 아님)"))
    executable = None if gate_state is None else str(gate_state) == EXECUTABLE_GATE
    defense = None if market_state is None else str(market_state) in MARKET_DEFENSE_STATES
    mult = None
    if monthly_multiplier is not None:
        try:
            mult = float(monthly_multiplier)
        except (TypeError, ValueError):
            mult = None
        if mult is not None and not math.isfinite(mult):
            mult = None
    return {
        "stage": stage,
        "stage_label": label,
        "decision_code": code,
        "dca_stage": str(decision.get("leveraged_dca_stage", "") or ""),
        "dca_multiple": str(decision.get("leveraged_dca_multiple", "") or ""),
        "recovery_state": str(decision.get("leveraged_recovery_state", "") or ""),
        "executable": executable,
        "market_defense": defense,
        "monthly_multiplier": mult,
        # The known gap the user asked to keep visible: a plan amount while the gate never executes.
        "plan_gate_mismatch": bool(executable is False and mult is not None and mult > 0),
        # C-3 (2026-11-25): the L3 cycle read (stock_lab_core.leverage_l3_policy). "L3 후보" is shown, but no
        # budget or tranche record is stored yet, so it never makes the row executable. None = not read.
        "l3_status": (decision.get("leveraged_l3") or {}).get("status") if isinstance(decision.get("leveraged_l3"), dict) else None,
        "l3_reasons": list((decision.get("leveraged_l3") or {}).get("reasons") or []) if isinstance(decision.get("leveraged_l3"), dict) else [],
    }


from stock_lab_core.report_build import register_loaded_source
register_loaded_source(__name__, __file__)
