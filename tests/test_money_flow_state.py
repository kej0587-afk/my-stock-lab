from stock_lab_core.money_flow import classify_money_flow_state


def test_money_flow_state_marks_negative_3m_positive_6m_as_weak_turn():
    state = classify_money_flow_state(
        ret_3m=-0.04,
        ret_6m=0.059,
        accel=-0.08,
        price_level=0.52,
    )

    assert state == "약세 전환"


def test_money_flow_state_keeps_positive_3m_deceleration_as_slowdown():
    state = classify_money_flow_state(
        ret_3m=0.038,
        ret_6m=0.12,
        accel=-0.50,
        price_level=0.48,
    )

    assert state == "둔화 경고"
