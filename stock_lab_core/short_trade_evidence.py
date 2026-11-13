"""Descriptive evidence quality, not a learned probability or investment gate."""

import hashlib

import pandas as pd

from stock_lab_core.chart_structure import build_parallel_channel
from stock_lab_core.soxl_short_observation import completed_hour_frame, completed_hour_grid, HOUR
from stock_lab_core.soxl_trade_plan import OHLC, price_plan, setup_from_channel
from stock_lab_core.short_trade_research import replay, summarize
from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)
VERSION = 1


def input_fingerprint(frames):
    digest = hashlib.sha256()
    for ticker, frame in sorted(frames.items()):
        digest.update(ticker.encode())
        digest.update(pd.util.hash_pandas_object(frame.reindex(columns=OHLC), index=True).values.tobytes())
    return digest.hexdigest()[:16]


def cohort_at(reference, instrument, start):
    """Fixed ex-ante bins; no price scan, outcome tuning or cross-symbol pooling."""
    if start not in instrument.index or start not in reference.index:
        return None
    prefix = reference.loc[:start].tail(6)
    own = instrument.loc[start]
    if len(prefix) != 6 or prefix[OHLC].isna().any().any():
        return None
    plan = price_plan(own.Close, own.Low)
    if not plan:
        return None
    risk = plan["risk_pct"]
    bucket = "<=1%" if risk <= 1 else "1~2%" if risk <= 2 else ">2%"
    momentum = "5봉 상승" if prefix.Close.iloc[-1] > prefix.Close.iloc[0] else "5봉 비상승"
    return bucket + " · " + momentum


def validation_state(policy):
    """Research reporting floors, never added to the user's investment thresholds."""
    stats = policy["stats"]
    if not stats["n"]:
        return "검증 불가", "완료 거래 표본 없음 · 승률은 0%가 아님"
    if stats["mean_pct"] <= 0:
        return "우위 미확인", "비용 후 전체 평균 손익이 0 이하"
    if stats["n"] < 30 or policy["late"]["n"] < 20:
        return "표본 부족", "전체 30건·후반 20건 미만 · 연구 표시 기준이며 투자 임계값 아님"
    if any(not policy[k]["n"] or policy[k]["mean_pct"] <= 0 for k in ("early", "late", "cost20")):
        return "안정성 미확인", "전반·후반 또는 비용 2배 조건에서 양의 평균이 유지되지 않음"
    return "전진검증 후보", "과거 조건별 평균은 양수 · 독립 실시간 검증 전 수익성 입증/매수 승인 아님"


def build_report(frames, schedule, captured, profile, cost_bps=10):
    report = replay(frames, schedule, captured, reference=profile["reference"],
                    instrument=profile["ticker"], rule=profile["rule"],
                    market_tz=profile["timezone"], cost_bps=cost_bps)
    report.update(profile=profile, fingerprint=input_fingerprint(frames), captured_at=captured,
                  cost_bps=cost_bps, evidence_version=VERSION)
    if not report["policies"]:
        return report
    grid = completed_hour_grid(schedule, captured)
    clean = {t: completed_hour_frame(f, grid)[0].reindex(grid) for t, f in frames.items()}
    for policy in report["policies"].values():
        for trade in policy["trades"]:
            trade["cohort"] = cohort_at(clean[profile["reference"]], clean[profile["ticker"]],
                                        trade["signal_time"] - HOUR)
        policy["validation"] = validation_state(policy)
    return report


def current_context(frames, schedule, now, profile):
    grid = completed_hour_grid(schedule, now)
    result = dict(issue="", setup=False, plan={}, cohort=None, as_of=None)
    if len(grid) < 140:
        return dict(result, issue="동일 연구 규칙의 완료 140시간봉 부족")
    clean = {}
    for ticker in dict.fromkeys((profile["reference"], profile["ticker"])):
        frame, issue = completed_hour_frame(frames.get(ticker), grid[-140:])
        if issue or len(frame) < 140 or frame[OHLC].isna().any().any():
            return dict(result, issue=f"{ticker}: 최신 연속 140시간봉 미확보 · 결측/거래정지/시각 불일치 가능")
        clean[ticker] = frame
    reference, own = clean[profile["reference"]], clean[profile["ticker"]]
    result["as_of"] = grid[-1] + HOUR
    channel = build_parallel_channel(reference)
    if channel and pd.Timestamp(channel["known_at"]) > reference.index[-1]:
        channel = {}
    setup, reason = setup_from_channel(reference, channel)
    result.update(plan=price_plan(own.Close.iloc[-1], own.Low.iloc[-1]),
                  setup=bool(setup), issue=reason.replace("SOXX", profile["reference"]),
                  cohort=cohort_at(reference, own, grid[-1]))
    active = schedule.loc[(schedule.market_open <= now) & (schedule.market_close > now)]
    if not active.empty and result["as_of"] <= active.market_open.iloc[0]:
        result.update(setup=False, issue="새 정규장 첫 완료 1시간봉 대기 · 전일 신호로 진입하지 않음")
    if not result["plan"]:
        result.update(setup=False, issue="종가·신호봉 저가 사이 양의 손절거리 없음")
    return result


def comparable_history(policy, current):
    if not current["setup"] or not current["cohort"] or current["as_of"] is None:
        return summarize([])
    trades = [t for t in policy["trades"] if t.get("cohort") == current["cohort"]
              and t["exit_time"] < current["as_of"]]
    return summarize(trades)
