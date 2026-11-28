"""Read-only provenance and bounded market-attachment replay; never permission.

No fetch, wall clock, new scores, sizing, account lookup or mutation of source rows.
The Today snapshot does not retain a complete order/final-check input envelope.
Consequently a passed screening replay MUST NOT become executable or count as zero.
"""
from collections import Counter
from copy import deepcopy
import hashlib
import json
import math

import pandas as pd

from stock_lab_core.execution_gate import build_execution_gate, GATE_EXECUTABLE
from stock_lab_core.portfolio import portfolio_flow_ticker_key
from stock_lab_core.sector_candidate_association import sector_market_from_row
from stock_lab_core.today_queue_session import LAST_RUN_KEY, ORIGIN_KEY, SIGNATURE_KEY, STALE_KEY

META_COLUMNS = ("점검결과출처", "점검결과상태", "점검원계산시각", "점검입력맥락", "점검재계산사유")
OBS_COLUMNS = ("시장만모의해제", "시장만모의해제_선별결과", "시장만모의해제_근거",
               "시장만모의해제_미확인항목", "시장만모의해제_실행가능", "시장만모의해제_확인범위", "시장만모의해제_증거출처")
CACHE_KEY = "today_market_observation_cache"
INPUTS_KEY = "today_observation_inputs"
SCOPE_NOTE = ("시장 연결 차단만 제외 · 원계산 행에 보존된 판정코드·문구·RR·"
              "MTF·돈흐름의 기존 선별게이트만 재검증 · 시장매크로 원판정 제외 재계산은 미완료 · 점수·판정·금액 불변")
UNVERIFIED = "당시 주문가능현금·환율·실행금액/예산·원정밀 비중·RR 원가격·구조/과열 전체 입력·정밀 최종체크"
FULL_CHECK_GAPS = "증권사 실제 주문가능액·확정 실행금액/월예산·RR/밸류/신규ETF/레버리지 포함 최종체크 전체"


def capture_observation_inputs(sink, *, cash, reserve, fx, macro, mode):
    """Copy existing calculation values only; account cash is NOT broker buying power."""
    fields = ("dd", "live_gap_shock", "day_ret", "structure_risk", "trend", "rs_label", "mtf_bias_label",
              "mtf_bias_text", "mfi", "rsi", "pct_b", "core_dca_rate", "core_dca_label", "bucket",
              "current_w", "target_w", "weight_gap", "buy_amt", "effective_total_asset", "core_dca_amt",
              "core_dca_pool", "rr_stop", "rr_target", "cur_p")
    result = {}
    for ticker, record in sink.items():
        post = record.get("post") or {}
        result[portfolio_flow_ticker_key(ticker)] = {
            "decision": {key: deepcopy(post[key]) for key in fields if key in post},
            "has_pos": record.get("has_pos"), "price_input_id": (record.get("row") or {}).get("가격입력ID"),
            "cash_input_krw": cash, "reserve_input_krw": reserve, "fx_input": fx,
            "macro": macro, "mode": mode,
        }
    return result


def _finite(value):
    try:
        return not isinstance(value, bool) and math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def replay_retained_final_checks(envelope, raw):
    """Use shared pure final-check rows, not the app's fetching final-check orchestrator."""
    from stock_lab_core.final_check_rows import build_risk_check_rows, build_portfolio_check_rows
    if not isinstance(envelope, dict) or envelope.get("price_input_id") != raw.get("가격입력ID"):
        return [], [], UNVERIFIED
    c = envelope.get("decision") or {}
    checks, verified = [], []
    core_known = _finite(c.get("core_dca_rate")) and isinstance(c.get("bucket"), str)
    risk_fields = ("dd", "day_ret", "mfi", "rsi", "pct_b")
    if (core_known and all(_finite(c.get(key)) for key in risk_fields)
            and all(isinstance(c.get(key), bool) for key in ("live_gap_shock", "structure_risk"))
            and all(isinstance(c.get(key), str) for key in ("trend", "rs_label", "mtf_bias_label"))):
        checks.extend(build_risk_check_rows(
            is_core_dca=c["core_dca_rate"] > 0 and c["bucket"] == "core",
            **{key: c[key] for key in (*risk_fields, "live_gap_shock", "structure_risk", "trend", "rs_label", "mtf_bias_label")},
            mtf_bias_text=c.get("mtf_bias_text", ""), core_dca_label=c.get("core_dca_label", "")))
        verified.append("정밀 구조/MTF/과열 공통체크")
    if (isinstance(envelope.get("has_pos"), bool) and all(_finite(c.get(key)) for key in ("target_w", "current_w"))
            and _finite(envelope.get("macro")) and all(isinstance(c.get(key), str) for key in ("trend", "rs_label"))):
        checks.extend(build_portfolio_check_rows(
            has_pos=envelope["has_pos"], target_w=c["target_w"], curr_w=c["current_w"],
            weight_gap=c["target_w"]-c["current_w"], macro_risk=envelope["macro"],
            trend=c["trend"], rs_label=c["rs_label"], price_vs_avg=math.nan))
        verified.append("정밀 비중/매크로/보유 공통체크")
    if all(_finite(envelope.get(key)) for key in ("cash_input_krw", "reserve_input_krw", "fx_input")) and all(
            _finite(c.get(key)) for key in ("buy_amt", "effective_total_asset")):
        verified.append("입력 예수금/예비금/환율/총액/부족액 보존 · 주문가능액 아님")
    gaps = [FULL_CHECK_GAPS]
    if not any(item.startswith("정밀 구조") for item in verified):
        gaps.append("원정밀 구조/과열 입력")
    if not any(item.startswith("정밀 비중") for item in verified):
        gaps.append("원정밀 비중/매크로 입력")
    if not any(item.startswith("입력 예수금") for item in verified):
        gaps.append("당시 현금/환율/총액/부족액 원값")
    return checks, verified, " · ".join(gaps)


def _text(value):
    return value.strip() if isinstance(value, str) else ""


def result_metadata(frame, state, *, run_summary, signature, account_context):
    """Display and CSV consume the same metadata, retaining calculation time."""
    reason = _text(frame.attrs.get(STALE_KEY)) or _text(state.get(STALE_KEY))
    signature_ok = bool(signature) and state.get(SIGNATURE_KEY) == signature
    context_ok = bool(account_context) and frame.attrs.get("portfolio_signal_context") == account_context
    if not reason and not signature_ok:
        reason = "입력 변경 · 입력 서명 불일치"
    if not reason and not context_ok:
        reason = "계좌·입력맥락 불일치 또는 미저장"
    origin = "새 전체 계산" if run_summary else state.get(ORIGIN_KEY, "세션 계산 재사용")
    return {"점검결과출처": origin,
            "점검결과상태": "현재 입력 달라 재계산 필요" if reason else origin,
            "점검원계산시각": _text(state.get(LAST_RUN_KEY)) or "미확인",
            "점검입력맥락": "일치" if signature_ok and context_ok and not reason else "미확인/불일치",
            "점검재계산사유": reason or "없음"}


def attach_result_metadata(frame, metadata):
    out = frame.copy(deep=True)
    out.attrs = deepcopy(frame.attrs)
    for key in META_COLUMNS:
        out[key] = metadata[key]
    return out


def metadata_frame(frame):
    columns = [key for key in META_COLUMNS if key in frame]
    if not columns:
        return pd.DataFrame([{key: "미확인" for key in META_COLUMNS}])
    return frame[columns].drop_duplicates().reset_index(drop=True)


def observation_frame(frame):
    return frame[[key for key in ("티커", "종목명", *META_COLUMNS, *OBS_COLUMNS)
                  if key in frame]].copy()


def attach_market_observation(displayed, original, metadata):
    """Replay ONLY the original row, not market-rewritten display prose/enrichment.

    Recovered sessions have no saved market-attachment clock: report unknown.
    Original dates and identity must match; never substitute today's account values.
    A residual veto is observable but a complete market-only permission is unknown.
    """
    out = displayed.copy(deep=True)
    out.attrs = deepcopy(displayed.attrs)
    sources = original.to_dict("records")
    keys = [portfolio_flow_ticker_key(row.get("티커")) for row in sources]
    counts = Counter(keys)
    shown_counts = Counter(portfolio_flow_ticker_key(row.get("티커")) for row in out.to_dict("records"))
    by_key = dict(zip(keys, sources))
    market_dates = {}
    for row in sources:
        market = sector_market_from_row({"티커": row.get("티커")})
        market_dates.setdefault(market, set()).add(_text(row.get("가격자료기준일")))
    observations = []
    for shown in out.to_dict("records"):
        key = portfolio_flow_ticker_key(shown.get("티커"))
        raw = by_key.get(key, {})
        missing = []
        market_dates_for_row = market_dates.get(sector_market_from_row({"티커": raw.get("티커")}), set())
        if len(market_dates_for_row) != 1 or "" in market_dates_for_row:
            missing.append("같은 시장 원자료 기준일 혼재/미확인")
        if metadata.get("점검입력맥락") != "일치":
            missing.append("계좌·입력맥락 불일치/미저장")
        if metadata.get("점검결과출처") != "새 전체 계산":
            missing.append("복원/재사용 결과의 원시장연결 시점 미보존")
        if not key or counts[key] != 1 or shown_counts[key] != 1:
            missing.append("동일 종목 원결과 유일 매칭 불가")
        for field in ("계산시각", "가격입력ID", "가격자료기준일"):
            if not _text(raw.get(field)) or raw.get(field) != shown.get(field):
                missing.append(field + " 불일치/미확인")
        if (_text(raw.get("지표마지막봉")) != _text(raw.get("가격자료기준일"))
                or shown.get("가격신선도") != "current"):
            missing.append("자료날짜/완료봉 정합성 미확인")
        for row in (raw, shown):
            if row.get("데이터상태") not in ("OK", "NORMAL", "정상"):
                missing.append("원결과/표시 데이터상태 미확인")
        for field in ("RSI", "MFI", "볼린저 %B", "RR값"):
            try:
                valid = not isinstance(raw.get(field), bool) and math.isfinite(float(raw[field]))
            except (KeyError, TypeError, ValueError):
                valid = False
            if not valid:
                missing.append(field + " 원입력 미확인")
        flow_present = any(_text(raw.get(field)) for field in ("돈흐름_판정", "돈흐름_후보군"))
        if flow_present and (raw.get("돈흐름신선도") != "aligned"
                             or raw.get("돈흐름_거래량기준일") != raw.get("가격자료기준일")):
            missing.append("원돈흐름 자료날짜/거래량 정합성 미확인")
        market = _text(shown.get("시장실행상태"))
        verified, gaps = [], UNVERIFIED
        status, gate_label, reason = "미확인", "미재생", " · ".join(dict.fromkeys(missing))
        if not missing and "시장방어" not in market:
            status = "시장 차단 없음" if market == "정상" else "미확인"
            reason = "시장 연결 차단 없음" if market == "정상" else "시장 상태 미확인"
        elif not missing:
            replay = deepcopy(raw)
            replay["시장실행상태"] = "정상"
            gate = build_execution_gate(replay)
            checks, verified, gaps = replay_retained_final_checks(original.attrs.get(INPUTS_KEY, {}).get(key), raw)
            verified.insert(0, "원계산 행의 선별게이트")
            gate_label = gate["게이트상태"]
            reason = gate["게이트근거"]
            evidence = set(gate.get("게이트근거ID", "").split("|"))
            market_in_original = bool(evidence & {"macro", "market"}) or any(
                row["점검항목"] == "매크로" and row["상태"] == "차단" for row in checks)
            if gate_label == GATE_EXECUTABLE:
                gate_label = "선별 통과 · 실행 미확인"
            elif gate_label == "데이터확인":
                status = "미확인"
            elif evidence & {"weight", "structure", "mtf", "rr", "pattern", "overheat", "flow", "quality"}:
                status = "다른 조건도 차단"
            # Macro is itself part of the market-only counterfactual, never an other-gate veto.
            blocks = [row for row in checks if row["상태"] == "차단" and row["점검항목"] != "매크로"]
            if blocks:
                status = "다른 조건도 차단"
                reason += " · " + " · ".join(row["점검항목"] + ": " + row["해석"] for row in blocks)
            if market_in_original:
                reason += " · 원판정에 시장조건 포함, 시장만 제외한 전체 재계산에 필요한 원입력 미보존"
            elif status == "미확인" and gate_label not in {"데이터확인", "선별 통과 · 실행 미확인"}:
                reason += " · 원판정의 시장/종목 조건 분리 미확인"
        observations.append({"시장만모의해제": status, "시장만모의해제_선별결과": gate_label,
                             "시장만모의해제_근거": reason,
                             "시장만모의해제_미확인항목": gaps,
                             "시장만모의해제_실행가능": "미확인",
                             "시장만모의해제_확인범위": " · ".join(verified) or "재생 전 정합성 확인 미완료",
                             "시장만모의해제_증거출처": "이번 계산 관찰" if not missing else "증거 미확인"})
    for field in OBS_COLUMNS:
        out[field] = pd.Series([row[field] for row in observations], index=out.index, dtype="object")
    return out


def _observation_key(original, displayed, *, signature, context, calculation_id):
    if not all((signature, context, calculation_id)):
        return ""
    raw = original.drop(columns=list(META_COLUMNS) + list(OBS_COLUMNS), errors="ignore")
    payload = {"version": 2, "calculation_id": calculation_id, "signature": signature, "context": context,
               "input": raw.to_json(orient="split", date_format="iso", double_precision=15),
               "envelope": original.attrs.get(INPUTS_KEY),
               "display_context": displayed[[key for key in ("티커", "가격입력ID", "가격신선도", "데이터상태", "시장실행상태")
                                               if key in displayed]].to_json(orient="split", date_format="iso")}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def reuse_or_build_market_observation(displayed, original, metadata, state, *, signature, context):
    """One session-local evidence record keyed to original calculation/account inputs.

    Rerenders reattach identical evidence without invoking any check. Changes in current
    market/data freshness invalidate reuse too. Legacy disk restores have no envelope.
    """
    key = _observation_key(original, displayed, signature=signature, context=context,
                           calculation_id=original.attrs.get("portfolio_signal_at"))
    cached = state.get(CACHE_KEY)
    eligible = metadata.get("점검입력맥락") == "일치" and bool(key)
    if (eligible and metadata.get("점검결과출처") != "새 전체 계산"
            and isinstance(cached, dict) and cached.get("key") == key):
        evidence = cached.get("columns")
        if isinstance(evidence, pd.DataFrame) and evidence.index.equals(displayed.index) and len(evidence) == len(displayed):
            out = displayed.copy(deep=True)
            out.attrs = deepcopy(displayed.attrs)
            for field in OBS_COLUMNS:
                out[field] = evidence[field].copy()
            out["시장만모의해제_증거출처"] = "동일 계산ID·서명·계좌맥락의 관찰 재사용"
            return out
    out = attach_market_observation(displayed, original, metadata)
    if eligible and metadata.get("점검결과출처") == "새 전체 계산":
        state[CACHE_KEY] = {"key": key, "columns": out[list(OBS_COLUMNS)].copy(deep=True)}
    elif not eligible:
        state.pop(CACHE_KEY, None)
    return out


def unheld_observation_tables(frame):
    """Explicit booleans only. Never infer unheld from an absent/zero-ish quantity."""
    unheld, unknown = [], []
    for row in frame.to_dict("records"):
        held = row.get("has_pos")
        qty = row.get("qty")
        known = isinstance(held, bool)
        if "qty" in row and (not _finite(qty) or float(qty) < 0 or (float(qty) > 0) != held):
            known = False
        if known and held:
            continue
        status = row.get("시장만모의해제", "미확인") if known else "미확인"
        reason = _text(row.get("시장만모의해제_근거"))
        if status not in {"시장만 차단", "다른 조건도 차단", "미확인"}:
            status, reason = "미확인", "시장 연결 차단 대상 아님 · " + reason
        item = {"종목": f"{_text(row.get('종목명'))} ({_text(row.get('티커'))})",
                "섹터·돈흐름 기준일": f"섹터 {_text(row.get('섹터RS기준일')) or '미확인'} / 돈흐름 {_text(row.get('돈흐름_기준일')) or '미확인'}",
                "실제 최종 게이트": _text(row.get("게이트상태")) or "미확인",
                "시장 차단 관찰": status,
                "남은 사유": reason + " · " + _text(row.get("시장만모의해제_미확인항목"))}
        if known:
            unheld.append(item)
        else:
            item["남은 사유"] = "보유 여부 미확인/수량 불일치 · " + item["남은 사유"]
            unknown.append(item)
    return pd.DataFrame(unheld), pd.DataFrame(unknown)


def render_result_observation(st, frame):
    if not isinstance(frame, pd.DataFrame) or frame.empty or "점검결과상태" not in frame:
        return
    for row in metadata_frame(frame).to_dict("records"):
        message = (f"{row['점검결과상태']} · 출처 {row['점검결과출처']} · "
                   f"원계산 {row['점검원계산시각']} · 입력맥락 {row['점검입력맥락']}")
        if row["점검입력맥락"] != "일치":
            st.warning(message + " · " + row["점검재계산사유"])
        else:
            st.caption(message)
    if "시장만모의해제" not in frame:
        return
    with st.expander("시장 차단만 모의 해제 · 읽기 전용 관찰"):
        st.caption(SCOPE_NOTE)
        st.caption("실제 실행가능 종목 수: 미확인 · 0개라는 뜻이 아닙니다. " + FULL_CHECK_GAPS + " 미검증")
        st.caption("실제 최종 게이트는 현재 오늘점검 표시값입니다. 정밀 최종 체크의 실행 허가와 다릅니다.")
        unheld, unknown = unheld_observation_tables(frame)
        if not unheld.empty:
            st.dataframe(unheld, hide_index=True, width="stretch")
        else:
            st.caption("보유 여부가 확인된 미보유 관찰 행 없음 · 실행가능 0건을 뜻하지 않습니다.")
        if not unknown.empty:
            st.caption(f"보유 여부 미확인 {len(unknown)}행 · 미보유 후보 수에서 제외")
            st.dataframe(unknown, hide_index=True, width="stretch")


from stock_lab_core.report_build import register_loaded_source
register_loaded_source(__name__, __file__)
