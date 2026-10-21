"""Offline semantic regressions, including the downloaded report (10) rows."""

from copy import deepcopy

import pytest

from stock_lab_core.report_economic_reading import economic_implication


def release(indicator="US_CPI", actual=0.6, previous=0.4, **changes):
    row = {"indicator": indicator, "period": "2026-09", "actual": actual,
           "previous": previous, "forecast": None, "unit": "%", "basis": "MoM",
           "status": "released"}
    row.update(changes)
    return row


@pytest.mark.parametrize("indicator,actual,previous,basis,unit,expected", [
    ("US_CPI", 0.6, 0.4, "MoM", "%", "전월비 소비자물가 상승 지속, 이전보다 상승률 확대"),
    ("US_CPI", 3.7, 3.4, "YoY", "%", "전년비 소비자물가 상승 지속, 이전보다 상승률 확대"),
    ("US_CORE_CPI", 0.3, 0.3, "MoM", "%", "전월비 근원 소비자물가 상승 지속, 이전보다 상승률 동일"),
    ("US_CORE_CPI", 2.6, 2.4, "YoY", "%", "전년비 근원 소비자물가 상승 지속, 이전보다 상승률 확대"),
    ("US_PPI", 1.3, 0.5, "MoM", "%", "생산자물가 상승 지속, 이전보다 상승률 확대"),
    ("US_PPI", 6.3, 5.6, "YoY", "%", "전년비 생산자물가 상승 지속"),
    ("US_NONFARM_PAYROLLS", 29, 133, "MoM", "thousand persons", "고용 증가 지속, 이전보다 증가폭 축소"),
    ("US_UNEMPLOYMENT", 4.2, 4.1, "level", "%", "실업률 수준: 이전 관측보다 높아짐"),
    ("US_FED_TARGET_UPPER", 4.0, 4.0, "level", "%", "연준 목표금리 상단 수준: 이전 관측과 같음"),
    ("KR_CPI", 2.9, 3.1, "YoY", "%", "전년비 한국 소비자물가 상승 지속, 이전보다 상승률 축소"),
    ("KR_EXPORTS", 83.7, 68.9, "YoY", "%", "전년비 한국 수출액 증가 지속, 이전보다 증가율 확대"),
])
def test_report10_observations(indicator, actual, previous, basis, unit, expected):
    result = economic_implication(release(indicator, actual, previous, basis=basis, unit=unit))
    assert expected in result
    assert "예상치 미연결로 서프라이즈 판단 보류" in result
    assert "예상치 상회" not in result and "예상치 하회" not in result


@pytest.mark.parametrize("actual", [None, "", "-", "NaN", float("nan"), float("inf"), True, False])
def test_missing_actual_is_not_neutral_or_unpublished(actual):
    result = economic_implication(release("US_RETAIL_SALES", actual, None, status="unavailable"))
    assert "발표치 미확인" in result and "중립 판단 아님" in result
    assert "미발표를 뜻하지 않음" in result
    assert "가능성" not in result and "예상치 부합" not in result


@pytest.mark.parametrize("status", ["pending", "scheduled", "예정"])
def test_pending_does_not_interpret_even_a_supplied_actual(status):
    result = economic_implication(release(actual=0.6, status=status))
    assert "확정 발표치 확인 전 해석 보류" in result
    assert "물가 압력 확대" not in result


@pytest.mark.parametrize("actual,previous,expected", [
    (0, 0, "보합 유지"), (0, 0.2, "상승에서 보합 전환"),
    (0.2, 0, "보합에서 상승 전환"), (-0.1, 0, "보합에서 하락 전환"),
    (0.2, 0.4, "상승 지속, 이전보다 상승률 축소"),
    (-0.2, -0.4, "하락 지속, 이전보다 하락률 축소"),
    (-0.4, -0.2, "하락 지속, 이전보다 하락률 확대"),
    (0.1, -0.1, "하락에서 상승 전환"), (-0.1, 0.1, "상승에서 하락 전환"),
])
def test_inflation_sign_is_distinct_from_change_in_rate(actual, previous, expected):
    assert expected in economic_implication(release(actual=actual, previous=previous))


def test_no_previous_does_not_invent_acceleration_from_history_or_cached_deltas():
    result = economic_implication(release(previous=None, actual_minus_previous=4,
                                         history=[{"period": "2026-08", "value": -4}]))
    assert "상승 관측" in result and "이전값 미확인" in result
    assert "비교 근거 부족" in result
    assert "상승률 확대" not in result and "압력 확대" not in result


@pytest.mark.parametrize("field,value", [("previous_basis", "YoY"), ("previous_unit", "index"),
                                         ("previous_basis", "unknown"),
                                         ("previous_seasonal_adjustment", "NSA"),
                                         ("previous_period", "2026-09")])
def test_incompatible_previous_is_not_compared(field, value):
    result = economic_implication(release(seasonal_adjustment="SA", **{field: value}))
    assert "이전값 비교기준·단위 불일치" in result
    assert "상승률 확대" not in result and "물가 압력 확대" not in result


@pytest.mark.parametrize("field,value", [("forecast_basis", "YoY"), ("forecast_unit", "index"),
                                         ("forecast_seasonal_adjustment", "NSA"),
                                         ("forecast_period", "2026-08")])
def test_incompatible_forecast_is_not_a_surprise(field, value):
    result = economic_implication(release(forecast=0.4, forecast_source="calendar",
                                         seasonal_adjustment="SA", **{field: value}))
    assert "예상치 비교기준·단위 불일치" in result
    assert "예상치 상회" not in result


def test_forecast_needs_source_and_precomputed_surprise_does_not_supply_it():
    result = economic_implication(release(forecast=0.4, actual_minus_forecast=0.2))
    assert "예상치 출처 미확인" in result and "예상치 상회" not in result
    missing = economic_implication(release(actual_minus_forecast=0.2, forecast_source="calendar"))
    assert "예상치 미연결" in missing and "예상치 상회" not in missing


@pytest.mark.parametrize("actual,forecast,expected", [(0.2, 0, "상회"), (0, 0, "부합"), (0, 0.2, "하회")])
def test_zero_actual_and_forecast_remain_valid(actual, forecast, expected):
    result = economic_implication(release(actual=actual, previous=None, forecast=forecast,
                                         forecast_source="calendar", forecast_unit="%", forecast_basis="MoM"))
    assert f"예상치 {expected}(이전값 비교와 별도)" in result
    assert "이전값 미확인" in result and "발표치 미확인" not in result


def test_previous_and_consensus_disagreement_is_explicit():
    result = economic_implication(release(actual=0.4, previous=0.3, forecast=0.5, forecast_source="calendar"))
    assert "상승률 확대" in result and "예상치 하회" in result
    assert "방향이 엇갈려" in result
    assert "물가 압력 확대와" not in result and "물가 압력 완화와" not in result


@pytest.mark.parametrize("indicator", ["US_CORE_PPI", "US_PCE", "US_CORE_PCE", "US_PCE_PRICE_INDEX",
                                       "US_CORE_PCE_PRICE_INDEX", "KR_CORE_CPI"])
def test_additional_price_measures(indicator):
    result = economic_implication(release(indicator, actual=0.2, previous=0.4))
    assert "상승률 축소" in result and "물가 압력 완화" in result


@pytest.mark.parametrize("indicator,basis", [("US_GDP", "QoQ"), ("US_REAL_GDP", "QoQ annualized"),
                                           ("US_RETAIL_SALES", "MoM"), ("US_CORE_RETAIL_SALES", "YoY")])
def test_growth_positive_but_slowing_is_not_contraction(indicator, basis):
    result = economic_implication(release(indicator, 1.0, 2.0, basis=basis))
    assert "증가 지속" in result and "감소 전환" not in result
    assert "실적 둔화 우려와 금리 부담 완화 가능성이 공존" in result
    if "GDP" in indicator:
        assert "전분기비" in result and "전월비" not in result
    else:
        assert "명목 판매액" in result


@pytest.mark.parametrize("actual,previous,expected", [(0, 0, "보합 유지"), (29, 133, "증가폭 축소"),
                                                     (-29, -133, "감소폭 축소"), (-133, 29, "증가에서 감소 전환")])
def test_payroll_change_is_not_employment_level(actual, previous, expected):
    result = economic_implication(release("US_NONFARM_PAYROLLS", actual, previous, unit="thousand persons"))
    assert expected in result
    assert "수준" not in result


@pytest.mark.parametrize("indicator", ["US_JOLTS", "US_JOLTS_JOB_OPENINGS", "US_JOB_OPENINGS"])
def test_job_openings_are_a_level_not_new_payroll_jobs(indicator):
    result = economic_implication(release(indicator, 7200, 7300, basis="level", unit="thousand persons"))
    assert "JOLTS 구인건수 수준: 이전 관측보다 낮아짐" in result
    assert "실제 신규 채용 증감은 아님" in result
    assert "노동시장 둔화 우려" in result


def test_unemployment_direction_is_inverse_to_labor_demand():
    rising = economic_implication(release("US_UNEMPLOYMENT", 4.2, 4.1, basis="level"))
    falling = economic_implication(release("US_UNEMPLOYMENT", 4.1, 4.2, basis="level"))
    alone = economic_implication(release("US_UNEMPLOYMENT", 4.2, None, basis="level"))
    assert "노동시장 둔화 우려" in rising and "노동참가율" in rising
    assert "금리 인하 지연 가능성" in falling
    assert "수준 관측" in alone and "낮아짐" not in alone and "높아짐" not in alone


@pytest.mark.parametrize("actual,previous,expected", [(4, 4, "동결"), (4, 4.25, "인하"), (4, 3.75, "인상")])
def test_policy_decisions_are_distinct_from_daily_upper_limit(actual, previous, expected):
    decision = economic_implication(release("US_FED_RATE_DECISION", actual, previous, basis="level"))
    daily = economic_implication(release("US_FED_TARGET_UPPER", actual, previous, basis="level"))
    assert f"정책금리 {expected} 관측" in decision
    assert "일별 목표상단 관측값" in daily and "새로운 FOMC 결정 확인은 아님" in daily
    assert f"정책금리 {expected}" not in daily


def test_no_previous_policy_value_cannot_identify_a_decision():
    result = economic_implication(release("KR_BASE_RATE", 3, None, basis="level"))
    assert "정책금리 수준 관측" in result and "인상·인하·동결 판단 불가" in result


@pytest.mark.parametrize("changes", [{"basis": "level", "unit": "index"}, {"basis": "unknown"},
                                    {"unit": "unknown"}, {"indicator": "US_GDP", "basis": "MoM"}])
def test_unknown_or_wrong_measure_is_not_reinterpreted(changes):
    assert "해석 보류" in economic_implication(release(**changes))


def test_unknown_indicator_and_empty_row_are_explicit():
    assert "지표 정의 미확인" in economic_implication(release("NOT_SUPPORTED"))
    assert "발표치 미확인" in economic_implication({})


def test_string_numbers_and_zero_previous_are_supported():
    result = economic_implication(release("US_NONFARM_PAYROLLS", "1,000", "0", unit="persons"))
    assert "보합에서 증가 전환" in result


def test_pure_reading_leaves_freshness_reactions_and_trading_to_caller():
    row = release(history=[{"period": "2026-08", "value": 0.4}],
                  release_at="2026-10-14", reaction="10Y -2.70bp", reaction_source="daily bars")
    original = deepcopy(row)
    result = economic_implication(row)
    assert row == original and economic_implication(row) == result
    assert economic_implication(dict(row, status="stale", reaction="10Y -10.10bp")) == result
    assert len(result) < 300
    assert all(word not in result for word in ("오늘", "주가 상승", "주가 하락", "매수", "매도", "bp", "반대 움직임"))
