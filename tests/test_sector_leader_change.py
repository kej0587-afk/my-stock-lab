"""'업종 1위 교체' from the same close series (2026-11-26, daily reading follow-up)."""
from stock_lab_core.report_daily_change import sector_leader_change


def _ctx(**prices):
    return {"sessions": {"US": "2026-11-25", "KR": "2026-11-26"}, "prices": prices}


def _obs(today, prior, date="2026-11-25", prev="2026-11-24", **extra):
    return dict(date=date, previous_date=prev, previous_return=prior, **{"return": today}, **extra)


def test_leader_change_is_reported_with_both_days():
    ctx = _ctx(SOXX=_obs(0.03, -0.01), XLE=_obs(-0.01, 0.02), XLK=_obs(0.01, 0.0))
    line = sector_leader_change(ctx, "US")
    assert line == ("미국 관측 업종 3개 중 1위 교체: 전 거래일(2026-11-24) 에너지(XLE) +2.00%"
                    " → 반도체(SOXX) +3.00%(2026-11-25 확정 종가)")


def test_same_leader_or_too_few_or_mixed_dates_say_nothing():
    assert sector_leader_change(_ctx(SOXX=_obs(0.03, 0.02), XLE=_obs(0.0, 0.01), XLK=_obs(0.01, 0.0)), "US") is None
    assert sector_leader_change(_ctx(SOXX=_obs(0.03, -0.01), XLE=_obs(-0.01, 0.02)), "US") is None
    mixed = _ctx(SOXX=_obs(0.03, -0.01), XLE=_obs(-0.01, 0.02, prev="2026-11-21"), XLK=_obs(0.01, 0.0))
    assert sector_leader_change(mixed, "US") is None
    stale = _ctx(SOXX=_obs(0.03, -0.01), XLE=_obs(-0.01, 0.02, date="2026-11-24"), XLK=_obs(0.01, 0.0))
    assert sector_leader_change(stale, "US") is None
    missing_prior = _ctx(SOXX=_obs(0.03, None), XLE=_obs(-0.01, 0.02), XLK=_obs(0.01, 0.0))
    assert sector_leader_change(missing_prior, "US") is None


def test_korean_sectors_use_the_korean_session():
    ctx = _ctx(**{"305540.KS": _obs(0.05, 0.0, date="2026-11-26", prev="2026-11-25"),
                  "396500.KS": _obs(0.01, 0.04, date="2026-11-26", prev="2026-11-25"),
                  "494670.KS": _obs(0.0, 0.01, date="2026-11-26", prev="2026-11-25")})
    assert sector_leader_change(ctx, "KR").startswith("한국 관측 업종 3개 중 1위 교체: 전 거래일(2026-11-25) 한국 반도체")


from stock_lab_core.report_daily_change import completed_event_changes  # noqa: E402


def test_completed_results_only_on_session_dates():
    ctx = {"sessions": {"US": "2026-11-25", "KR": "2026-11-26"},
           "central_bank_results": [{"bank": "FOMC", "status": "official", "action": "hold", "date": "2026-11-25",
                                     "release_at": "2026-11-26T04:00:00+09:00"},
                                    {"bank": "BOJ", "status": "missing", "date": "2026-11-26"}]}
    pipeline = {"events": [{"event": "NVDA earnings", "event_status": "released", "date": "2026-11-25"},
                           {"event": "AAPL earnings", "event_status": "scheduled", "date": "2026-11-25"},
                           {"event": "MSFT earnings", "event_status": "released", "date": "2026-10-28"}]}
    changes = completed_event_changes(ctx, pipeline)
    assert len(changes) == 2
    assert changes[0].startswith("FOMC 정책 결정 발표 완료: 동결(") and "공식 성명" in changes[0]
    assert changes[1].startswith("NVDA earnings 실적 발표 완료(2026-11-25, 공식 결과 확인")
    assert completed_event_changes({"sessions": {}}, pipeline) == []
