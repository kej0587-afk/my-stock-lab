"""Reject demonstrably ineligible US extended quotes, without repricing providers.

Unknown timestamps, plain/manual floats and regular-close fallbacks retain their
existing contract. This repairs data eligibility, not investment policy or TTL.
"""
from datetime import datetime, timezone
import re

import pandas as pd

from stock_lab_core.quote_observation import quote_provenance
from stock_lab_core.report_build import register_loaded_source
from stock_lab_core.report_session import us_extended_session

register_loaded_source(__name__, __file__)


def decision_quote_rejection(value, ticker, *, now=None, manual=False):
    """Return a reason only for known-ineligible, timed US extended observations."""
    if manual:
        return ""
    evidence = quote_provenance(value)
    session = evidence.get("session")
    if session not in {"pre", "post", "day", "overnight"} or not evidence.get("observed_at"):
        return ""
    symbol = str(ticker).strip().upper()
    if not re.fullmatch(r"[A-Z]{1,6}(?:[-.][A-Z])?", symbol):
        return ""
    if evidence["symbol"] != symbol:
        return "시세 종목 불일치"
    clock = pd.Timestamp(now if now is not None else datetime.now(timezone.utc))
    if clock.tzinfo is None:
        raise ValueError("Decision quote clock must have a timezone")
    observed = pd.Timestamp(evidence["observed_at"])
    age = (clock - observed).total_seconds()
    if age < 0:
        return "미래 시각의 시간외 시세"
    # Same 20-minute eligibility as report_quotes.extended_quote_observation.
    # Bar-start evidence is checked as supplied; never invent a later trade time.
    if age > 1200:
        return "시간외 시세 지연(20분 초과)"
    window = us_extended_session(clock.to_pydatetime())
    expected = {"pre": "프리마켓", "post": "애프터마켓",
                "day": "데이마켓(미국 야간)", "overnight": "데이마켓(미국 야간)"}[session]
    if (not window or window["label"] != expected
            or not pd.Timestamp(window["start"]) <= observed < pd.Timestamp(window["end"])):
        return "현재 시간외 세션과 불일치"
    return ""


def _quote_assessment(value, ticker, *, now=None, manual=False, context=None):
    """Bind one calculation's adjudication to the exact supplied observation."""
    evidence = quote_provenance(value)
    symbol = str(ticker).strip().upper()
    if (manual or evidence.get("session") not in {"pre", "post", "day", "overnight"}
            or not evidence.get("observed_at")
            or not re.fullmatch(r"[A-Z]{1,6}(?:[-.][A-Z])?", symbol)):
        return {}
    binding = {"ticker": symbol, "observation": evidence}
    previous = (getattr(context[0], "attrs", {}).get("decision_quote_assessment")
                if context is not None else None)
    if isinstance(previous, dict) and previous.get("input") == binding:
        return dict(previous)
    clock = pd.Timestamp(now if now is not None else datetime.now(timezone.utc))
    return {"input": binding, "checked_at": clock.isoformat(),
            "rejection": decision_quote_rejection(value, ticker, now=clock, manual=manual)}


def prepare_eligible_live_context(df, live_price, ticker, indicator_builder, *,
                                  now=None, manual=False, apply_live_price_with_indicators=None,
                                  _assessment=None):
    """Shared chart/Today preparation; preserve the existing three-value contract."""
    if apply_live_price_with_indicators is None:
        from stock_lab_core.decision_engine import apply_live_price_with_indicators
    assessment = (_assessment if _assessment is not None else
                  _quote_assessment(live_price, ticker, now=now, manual=manual))
    reason = assessment.get("rejection", "")
    if reason:
        source = df.copy(deep=True)
        source.attrs["decision_quote_rejection"] = reason
        source.attrs["decision_quote_assessment"] = assessment
        return source, False, ""
    # Eligibility has already been decided. A wrapper callback must not read a
    # second clock at the 20-minute boundary. Provenance stays in the assessment.
    result, applied, issue = apply_live_price_with_indicators(
        df, float(live_price) if assessment else live_price, ticker, indicator_builder)
    if assessment:
        result = result.copy(deep=True)
        result.attrs["decision_quote_assessment"] = assessment
    return result, applied, issue


def prepare_decision_quote_context(df, live_price, ticker, indicator_builder, *,
                                   apply_live_price_with_indicators, context=None, now=None, manual=False):
    """Use the shared preparation decision, including when wall time has advanced.

    A supplied context belongs to this calculation, not a cross-run quote cache.
    Changed price/timestamp/provider/session cannot reuse another adjudication.
    """
    assessment = _quote_assessment(live_price, ticker, now=now, manual=manual, context=context)
    if not assessment:
        return live_price, context
    previous = (getattr(context[0], "attrs", {}).get("decision_quote_assessment")
                if context is not None else None)
    if previous != assessment:
        context = prepare_eligible_live_context(df, live_price, ticker, indicator_builder,
            apply_live_price_with_indicators=apply_live_price_with_indicators, _assessment=assessment)
    return (0.0 if assessment["rejection"] else live_price), context
