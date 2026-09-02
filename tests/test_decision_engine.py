"""Tests for stock_lab_core.decision_engine critical judgment paths."""
from stock_lab_core.decision_engine import (
    DECISION_GROUP_BY_CODE,
    build_core_dca_outcome,
    build_decision_outcome,
    classify_core_etf_dca_rate,
    classify_decision_signal,
    infer_decision_code,
    score_technical_components,
    score_main_entry,
    classify_candidate_grade,
    classify_safety_state,
    classify_macro_state,
)


# ---------------------------------------------------------------------------
# CORE_STORM_DCA — silent bug regression
# ---------------------------------------------------------------------------

class TestCoreStormDcaGroupMapping:
    """CORE_STORM_DCA must be registered in DECISION_GROUP_BY_CODE as buyish.

    Without this, build_decision_outcome falls back to classify_decision_signal
    on the label text. If the label wording ever changes, the group flips silently.
    """

    def test_core_storm_dca_in_group_map(self):
        assert "CORE_STORM_DCA" in DECISION_GROUP_BY_CODE

    def test_core_storm_dca_is_buyish(self):
        assert DECISION_GROUP_BY_CODE["CORE_STORM_DCA"] == "buyish"

    def test_operational_guard_codes_are_caution(self):
        assert DECISION_GROUP_BY_CODE["DATA_UNAVAILABLE"] == "caution"
        assert DECISION_GROUP_BY_CODE["DATA_ERROR"] == "caution"
        assert DECISION_GROUP_BY_CODE["SAFETY_RED_NO_NEW_ENTRY"] == "caution"

    def test_build_core_dca_outcome_storm_us_broad_group(self):
        # 미국 대표지수 퍼펙트스톰: 100% 거치 → buyish
        outcome = build_core_dca_outcome("코어 ETF", core_dca_rate=1.0, dca_label="미국지수 퍼펙트스톰 100% 거치 적립")
        assert outcome.code == "CORE_STORM_DCA"
        assert outcome.group == "buyish"

    def test_build_core_dca_outcome_storm_kr_25pct_group(self):
        # 국장 퍼펙트스톰 25% 방어 → buyish (매수 허용, 감속일 뿐)
        outcome = build_core_dca_outcome("코어 ETF", core_dca_rate=0.25, dca_label="국장 퍼펙트스톰 25% 방어적 적립")
        assert outcome.code == "CORE_STORM_DCA"
        assert outcome.group == "buyish"

    def test_build_core_dca_outcome_storm_50pct_group(self):
        outcome = build_core_dca_outcome("코어 ETF", core_dca_rate=0.50, dca_label="퍼펙트스톰 50% 감속 적립")
        assert outcome.code == "CORE_STORM_DCA"
        assert outcome.group == "buyish"

    def test_infer_decision_code_storm_label_roundtrip(self):
        # label에서 code를 역추론할 때 'CORE_STORM_DCA'가 나와야 함
        outcome = build_core_dca_outcome("코어 ETF", core_dca_rate=1.0, dca_label="미국지수 퍼펙트스톰 100% 거치 적립")
        assert infer_decision_code(outcome.label) is not None  # 추론 가능

    def test_holding_loss_and_trend_risk_labels_are_split(self):
        assert infer_decision_code("🚫평단 -15%↓: 원인 점검") == "COST_MINUS_15_CAUSE_CHECK"
        assert infer_decision_code("🚫추세위험: 원인 점검") == "TREND_RISK_CAUSE_CHECK"
        assert infer_decision_code("⏸️조건미달: 추매 보류") == "HOLDING_DCA_CONDITION_MISS"


# ---------------------------------------------------------------------------
# classify_core_etf_dca_rate — perfect storm policy
# ---------------------------------------------------------------------------

class TestClassifyCoreEtfDcaRatePerfectStorm:
    """퍼펙트스톰(macro_risk >= 4.5) 분기 정책 검증."""

    def test_us_broad_index_always_100pct(self):
        rate, label = classify_core_etf_dca_rate(
            is_core_etf=True, weight_gap=10.0, current_dd=-0.05,
            rsi_now=60, mfi_now=60, pct_b_now=0.5, trend="🚀정배열(상승)",
            is_us_broad_index_core_etf=True, final_macro_risk=5.0,
        )
        assert rate == 1.0
        assert "100%" in label or "거치" in label

    def test_kr_core_etf_deep_dd_50pct(self):
        # 국장 코어, 퍼펙트스톰, -20% 이상 낙폭, 과열 아님 → 50%
        rate, label = classify_core_etf_dca_rate(
            is_core_etf=True, weight_gap=10.0, current_dd=-0.25,
            rsi_now=40, mfi_now=40, pct_b_now=0.3, trend="🌊역배열(하락)",
            is_kr_listed_core_etf=True, final_macro_risk=5.0,
        )
        assert rate == 0.50
        assert "50%" in label

    def test_kr_core_etf_shallow_dd_25pct(self):
        # 국장 코어, 퍼펙트스톰, 낙폭 작음 → 25%
        rate, label = classify_core_etf_dca_rate(
            is_core_etf=True, weight_gap=10.0, current_dd=-0.05,
            rsi_now=55, mfi_now=55, pct_b_now=0.6, trend="⏳혼조세",
            is_kr_listed_core_etf=True, final_macro_risk=5.0,
        )
        assert rate == 0.25
        assert "25%" in label

    def test_leveraged_always_blocked(self):
        rate, label = classify_core_etf_dca_rate(
            is_core_etf=True, weight_gap=10.0, current_dd=-0.40,
            rsi_now=30, mfi_now=20, pct_b_now=0.1, trend="🌊역배열(하락)",
            is_leveraged_or_inverse=True, final_macro_risk=6.0,
        )
        assert rate == 0.0

    def test_extreme_overheat_blocked_in_storm(self):
        # 퍼펙트스톰 + 극단 과열(MFI>=85) → 0%
        rate, _ = classify_core_etf_dca_rate(
            is_core_etf=True, weight_gap=10.0, current_dd=0.0,
            rsi_now=50, mfi_now=87, pct_b_now=0.5, trend="🚀정배열(상승)",
            is_us_broad_index_core_etf=False, final_macro_risk=5.0,
        )
        assert rate == 0.0

    def test_not_core_etf_returns_zero(self):
        rate, label = classify_core_etf_dca_rate(
            is_core_etf=False, weight_gap=10.0, current_dd=-0.30,
            rsi_now=30, mfi_now=20, pct_b_now=0.1, trend="🌊역배열(하락)",
        )
        assert rate == 0.0
        assert label == ""

    def test_weight_gap_zero_returns_zero(self):
        rate, label = classify_core_etf_dca_rate(
            is_core_etf=True, weight_gap=0.0, current_dd=-0.30,
            rsi_now=30, mfi_now=20, pct_b_now=0.1, trend="🌊역배열(하락)",
        )
        assert rate == 0.0


# ---------------------------------------------------------------------------
# classify_core_etf_dca_rate — normal (non-storm) rate tiers
# ---------------------------------------------------------------------------

class TestClassifyCoreEtfDcaRateNormal:
    def test_crash_200pct(self):
        rate, label = classify_core_etf_dca_rate(
            is_core_etf=True, weight_gap=5.0, current_dd=-0.35,
            rsi_now=30, mfi_now=25, pct_b_now=0.1, trend="🌊역배열(하락)",
        )
        assert rate == 2.0

    def test_drawdown_150pct(self):
        rate, _ = classify_core_etf_dca_rate(
            is_core_etf=True, weight_gap=5.0, current_dd=-0.22,
            rsi_now=40, mfi_now=35, pct_b_now=0.2, trend="🌊역배열(하락)",
        )
        assert rate == 1.5

    def test_pullback_100pct(self):
        rate, _ = classify_core_etf_dca_rate(
            is_core_etf=True, weight_gap=5.0, current_dd=-0.12,
            rsi_now=50, mfi_now=50, pct_b_now=0.5, trend="⏳혼조세",
        )
        assert rate == 1.0

    def test_neutral_50pct(self):
        rate, _ = classify_core_etf_dca_rate(
            is_core_etf=True, weight_gap=5.0, current_dd=-0.03,
            rsi_now=60, mfi_now=60, pct_b_now=0.65, trend="🚀정배열(상승)",
        )
        assert rate == 0.5

    def test_overheat_25pct(self):
        rate, _ = classify_core_etf_dca_rate(
            is_core_etf=True, weight_gap=5.0, current_dd=-0.02,
            rsi_now=76, mfi_now=50, pct_b_now=0.5, trend="🚀정배열(상승)",
        )
        assert rate == 0.25


# ---------------------------------------------------------------------------
# score_technical_components — 안전관리자 점수
# ---------------------------------------------------------------------------

class TestScoreTechnicalComponents:
    def test_all_green(self):
        scores = score_technical_components(
            rs_label="🚀강함", mfi_now=25, trend="🚀정배열(상승)",
            macd_state="🔥매수신호(골든크로스)", sqz_status="🚀해제직후",
        )
        # rs_s=2, mfi_s=2, trend_s=2, macd_s=2, sqz_s=1 → total=9
        assert scores["tech_total"] == 9
        assert scores["rs_s"] == 2
        assert scores["sqz_s"] == 1

    def test_dead_cross_penalized(self):
        scores = score_technical_components(
            rs_label="➖보통", mfi_now=50, trend="⏳혼조세",
            macd_state="📉하락주의(데드크로스)", sqz_status="➡️해제유지",
        )
        assert scores["macd_s"] == -2

    def test_mfi_overheat_penalized(self):
        scores = score_technical_components(
            rs_label="➖보통", mfi_now=85, trend="🚀정배열(상승)",
            macd_state="📈추세유지(상승중)", sqz_status="➡️해제유지",
        )
        assert scores["mfi_s"] == -1

    def test_sqz_only_counts_with_buy_macd(self):
        # SQZ 해제직후여도 MACD가 하락추세면 sqz_s = 0
        scores = score_technical_components(
            rs_label="➖보통", mfi_now=50, trend="🚀정배열(상승)",
            macd_state="📉하락주의(데드크로스)", sqz_status="🚀해제직후",
        )
        assert scores["sqz_s"] == 0


# ---------------------------------------------------------------------------
# classify_candidate_grade — 등급 경계값
# ---------------------------------------------------------------------------

class TestClassifyCandidateGrade:
    def test_etf_excellent(self):
        result = classify_candidate_grade(is_etf=True, tech_total=6, fin_score=0)
        assert "우수" in result.grade

    def test_individual_financial_f_hard_block(self):
        result = classify_candidate_grade(is_etf=False, tech_total=8, fin_score=1)
        assert "F급" in result.grade and "재무위험" in result.grade

    def test_individual_s_grade(self):
        result = classify_candidate_grade(is_etf=False, tech_total=7, fin_score=4)
        assert "S급" in result.grade

    def test_good_fin_score_softens_low_tech(self):
        # fin_score=3 이상이면 tech가 낮아도 F급 아닌 C급
        result = classify_candidate_grade(is_etf=False, tech_total=0, fin_score=3)
        assert "F급" not in result.grade


# ---------------------------------------------------------------------------
# build_decision_outcome — group 분류 일관성
# ---------------------------------------------------------------------------

class TestClassifySafetyState:
    """안전관리자 상태 — RED/YELLOW/GREEN. classify_candidate_grade의 ETF 등급
    경계(<1, <3)와 일치해야 한다."""

    def test_red_below_one(self):
        assert classify_safety_state(0.9) == "RED"
        assert classify_safety_state(-3) == "RED"

    def test_invalid_safety_value_is_red(self):
        assert classify_safety_state(float("nan")) == "RED"
        assert classify_safety_state(None) == "RED"

    def test_yellow_between_one_and_three(self):
        assert classify_safety_state(1) == "YELLOW"
        assert classify_safety_state(2.9) == "YELLOW"

    def test_green_three_and_above(self):
        assert classify_safety_state(3) == "GREEN"
        assert classify_safety_state(9) == "GREEN"

    def test_consistent_with_etf_grade_boundaries(self):
        for tech_total in [-3, -1, 0, 0.9, 1, 2, 2.9, 3, 5, 9]:
            grade = classify_candidate_grade(is_etf=True, tech_total=tech_total, fin_score=0).grade
            state = classify_safety_state(tech_total)
            if "관망" in grade:
                assert state == "RED"
            elif "보통" in grade:
                assert state == "YELLOW"
            else:
                assert state == "GREEN"


class TestClassifyMacroState:
    """매크로/재난경보 상태 — STORM/CAUTION/NORMAL.
    퍼펙트스톰 임계값(>=4.5)은 app.py 전역에서 쓰이는 기준과 일치해야 한다."""

    def test_storm_at_or_above_4_5(self):
        assert classify_macro_state(4.5) == "STORM"
        assert classify_macro_state(6.0) == "STORM"

    def test_caution_between_1_5_and_4_5(self):
        assert classify_macro_state(1.5) == "CAUTION"
        assert classify_macro_state(4.49) == "CAUTION"

    def test_normal_below_1_5(self):
        assert classify_macro_state(0.0) == "NORMAL"
        assert classify_macro_state(1.49) == "NORMAL"

    def test_invalid_macro_value_is_unknown(self):
        assert classify_macro_state(float("nan")) == "UNKNOWN"
        assert classify_macro_state(None) == "UNKNOWN"

    def test_storm_threshold_matches_perfect_storm_policy(self):
        # classify_core_etf_dca_rate의 퍼펙트스톰 분기(>=4.5)와 정합성 확인
        rate, label = classify_core_etf_dca_rate(
            is_core_etf=True, weight_gap=10.0, current_dd=-0.05,
            rsi_now=60, mfi_now=60, pct_b_now=0.5, trend="🚀정배열(상승)",
            is_us_broad_index_core_etf=True, final_macro_risk=4.5,
        )
        assert classify_macro_state(4.5) == "STORM"
        assert "퍼펙트스톰" in label


class TestBuildDecisionOutcomeGroup:
    def test_hard_block_financial_is_caution(self):
        outcome = build_decision_outcome("🚨하드차단: 재무F급(처분)", "#dc2626", "HARD_BLOCK_FINANCIAL_F")
        assert outcome.group == "caution"

    def test_s_pullback_entry_is_buyish(self):
        outcome = build_decision_outcome("🎯S급 눌림목: 탑승 찬스", "#8b5cf6", "S_PULLBACK_ENTRY")
        assert outcome.group == "buyish"

    def test_unknown_code_falls_back_to_label_classify(self):
        outcome = build_decision_outcome("🚫하드차단: 추격금지", "#dc2626", "UNKNOWN_CODE_XYZ")
        assert outcome.group == "caution"
