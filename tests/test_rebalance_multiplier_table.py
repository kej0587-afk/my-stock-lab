"""B-3 (2026-11-24): code-based rebalance multipliers equal the old label parse."""
from stock_lab_core import decision_engine as de
from stock_lab_core.rebalance_multiplier import (
    POLICY_MULTIPLIER_BY_CODE, decision_signal_multiplier, legacy_label_multiplier,
)
from stock_lab_core.rebalance_multiplier_table import (
    KNOWN_LABELS_BY_CODE, MULTIPLIER_BY_CODE, MULTIPLIER_BY_CODE_LABEL, MULTIPLIER_BY_CORE_STAGE,
)
from stock_lab_core.monthly_rebalance import build_base_allocations

BUCKETS = ("core", "swing", "leverage", "Core", "unknown")
DIPS = (-1, 0, 1, 2, 3, 4)


def test_every_known_label_gives_the_old_multiplier():
    checked = 0
    for code, labels in KNOWN_LABELS_BY_CODE.items():
        if code in POLICY_MULTIPLIER_BY_CODE:  # approved corrections, checked below
            continue
        for label in labels:
            for bucket in BUCKETS:
                for dip in DIPS:
                    new = decision_signal_multiplier({"decision_code": code, "dec": label}, bucket, dip_level=dip)
                    assert new == legacy_label_multiplier(label, bucket, dip_level=dip), (code, label, bucket, dip)
                    checked += 1
    assert checked > 3000


def test_core_dca_codes_follow_the_stage_for_every_prefix():
    for (code, stage), _ in MULTIPLIER_BY_CORE_STAGE.items():
        for prefix in ("🧱코어", "🧱코어 ETF", "🧱신규 코어 ETF"):
            for rate in (0.25, 0.5, 1.0, 1.5, 2.0):
                outcome = de.build_core_dca_outcome(prefix, rate, stage)
                if outcome.code != code:
                    continue
                decision = {"decision_code": code, "dec": outcome.label, "core_dca_label": stage, "core_dca_rate": rate}
                for bucket in BUCKETS:
                    for dip in DIPS:
                        assert decision_signal_multiplier(decision, bucket, dip_level=dip) == \
                            legacy_label_multiplier(outcome.label, bucket, dip_level=dip), (code, stage, prefix, bucket)


def test_table_shape_and_unknown_labels_fall_back_to_the_old_parse():
    assert len(MULTIPLIER_BY_CODE) > 100 and len(MULTIPLIER_BY_CORE_STAGE) == 12
    assert {code for code, _ in MULTIPLIER_BY_CODE_LABEL} == {"LEVERAGED_DAILY_DROP_NO_ADD", "LEVERAGED_RECOVERY_DCA_BLOCK"}
    odd = {"decision_code": "S_PULLBACK_ENTRY", "dec": "🎯S급 눌림목: 탑승 찬스 / 추매금지"}
    assert decision_signal_multiplier(odd, "core") == legacy_label_multiplier(odd["dec"], "core") == 0.0
    assert decision_signal_multiplier("즉시투입 예수금", "core") == legacy_label_multiplier("즉시투입 예수금", "core")
    assert decision_signal_multiplier(None, "swing") == legacy_label_multiplier("-", "swing")


def test_monthly_plan_passes_the_decision_only_when_known():
    import pandas as pd

    seen = []

    def multiplier(tap, bucket, dip_level=0, decision=None):
        seen.append(decision)
        return 1.0

    eligible = pd.DataFrame([{"티커": "QQQ", "자산명": "QQQ", "목표비중": 10.0, "bucket": "core", "현재가": 1.0,
                              "매입가": 1.0, "보유량": 1.0, "is_etf": True}])
    decision = {"decision_code": "CORE_NEUTRAL_DCA", "dec": "x"}
    build_base_allocations(eligible, 10.0, 100.0, {"QQQ": "x"}, set(), multiplier, signal_decisions={"QQQ": decision})
    build_base_allocations(eligible, 10.0, 100.0, {"QQQ": "x"}, set(), lambda tap, bucket, dip_level=0: seen.append("old") or 1.0)
    assert seen == [decision, "old"]


def test_a4_profit_take_review_never_buys_in_monthly_plan():
    assert set(POLICY_MULTIPLIER_BY_CODE) == {"PROFIT_TAKE_REVIEW"}
    label = KNOWN_LABELS_BY_CODE["PROFIT_TAKE_REVIEW"][0]
    assert legacy_label_multiplier(label, "core") == legacy_label_multiplier(label, "swing") == 1.0  # old misreading
    for dec in (label, "다른 문구"):
        for bucket in ("core", "swing", "leverage"):
            for dip in DIPS:
                assert decision_signal_multiplier({"decision_code": "PROFIT_TAKE_REVIEW", "dec": dec}, bucket, dip) == 0.0
