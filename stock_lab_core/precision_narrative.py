"""Render the existing precision narrative without changing decision policy."""

from collections.abc import Mapping

import numpy as np

from stock_lab_core.asset_classifier import is_fin_score_exempt_asset, is_leveraged_or_inverse_product
from stock_lab_core.decision_engine import build_sideways_quality_state as _build_sideways_quality_state
from stock_lab_core.execution_gate import GATE_DATA_CHECK, GATE_DEFENSE, GATE_EXECUTABLE
from stock_lab_core.formatters import clean_bool, clean_float, escape_html_value, finite_num, format_currency


def align_precision_narrative_display(lines, border_color, workflow, *, entry_hint="", decision_code=""):
    """Apply an already computed gate to prose, leaving technical inputs intact."""
    aligned = list(lines)
    if not aligned or not isinstance(workflow, Mapping) or "게이트상태" not in workflow:
        return aligned, border_color
    gate = workflow.get("게이트상태")
    if gate == GATE_EXECUTABLE:
        return aligned, border_color
    reason = escape_html_value(workflow.get("게이트근거") or "실행 게이트 재확인 필요")
    aligned[0] = (
        f"<b>오늘 결론</b>: <b>실행 보류</b> · {escape_html_value(gate or '미확인')} · {reason}. "
        "기술적 후보 신호와 실제 실행 허용은 별도입니다."
    )
    if len(aligned) > 1:
        aligned[1] = aligned[1].replace("<b>📋 현재 판정</b>", "<b>기술적 원신호</b>", 1)
    # Entry-only prose must not override the gate; holding/exit guidance stays intact.
    if decision_code in {"QUALITY_PULLBACK_ENTRY", "TREND_PULLBACK_EXPLORE", "CORE_ETF_DCA_BUY"}:
        if entry_hint and entry_hint in aligned:
            aligned[aligned.index(entry_hint)] = (
                f"<b>신규/추가 진입 보류</b>: {reason}. 조건 해소 후 원신호를 다시 확인합니다."
            )
    return aligned, "#ef4444" if gate in {GATE_DEFENSE, GATE_DATA_CHECK} else "#d97706"


def build_precision_narrative(name, tkr, c, fin_score, has_p, my_p, *, is_etf=None,
                              describe_fvg_plain,
                              build_sideways_quality_state=_build_sideways_quality_state):
    """
    정밀관측소 차트 아래 표시할 종합 서술형 해설.
    외부 API 없이 이미 계산된 c 딕셔너리와 fin_score만 사용합니다.
    """
    dec         = c.get("dec", "")
    grade       = c.get("grade", "")
    t_score     = c.get("t_score", 0)
    tech_total  = c.get("tech_total", 0)
    trend       = c.get("trend", "")
    rs_label    = c.get("rs_label", "")
    rs_slope    = c.get("rs_slope_label", "")
    rsi         = c.get("rsi", 0.0)
    mfi         = c.get("mfi", 0.0)
    pct_b       = c.get("pct_b", 0.0)
    macd        = c.get("macd", "")
    sqz         = c.get("sqz", "")
    ext_struct  = c.get("ext_structure", "")
    int_struct  = c.get("int_structure", "")
    int_event   = c.get("int_event", "None")
    ext_event   = c.get("ext_event", "None")
    fvg_type    = c.get("fvg_type", "없음")
    fvg_active  = c.get("fvg_active", False)
    fvg_top     = c.get("fvg_top", 0)
    fvg_bottom  = c.get("fvg_bottom", 0)
    pd_zone     = c.get("pd_zone", "")
    smc_action  = c.get("smc_action", "")
    smc_insight = c.get("smc_insight", "")
    sector_flow = c.get("sector_flow_state", "-")
    is_52w      = c.get("is_52w_breakout", False)
    rr_ratio    = c.get("rr_ratio")
    rr_target   = c.get("rr_target", 0)
    rr_stop     = c.get("rr_stop", 0)
    rr_target_is_projection = bool(c.get("rr_target_is_projection", False))
    rr_target_source = str(c.get("rr_target_source", "") or "차트 구조 목표가")
    cur_p       = c.get("cur_p", 0)
    day_ret     = c.get("day_ret", 0.0)
    day_ret_label = c.get("day_ret_label", "전일등락")
    regular_day_ret = clean_float(c.get("regular_day_ret"), np.nan)
    live_ref_ret = clean_float(c.get("live_ref_ret"), np.nan)
    vol_ratio   = clean_float(c.get("vol_ratio"), np.nan)
    vol_ma20    = clean_float(c.get("vol_ma20"), np.nan)
    last_volume = clean_float(c.get("last_volume"), np.nan)
    vol_valid_count = int(clean_float(c.get("vol_valid_count"), 0))
    ma5         = c.get("ma5", 0)
    ma20        = c.get("ma20", 0)
    decision_code = c.get("decision_code", "")
    fvg_plain_label, fvg_plain_note = describe_fvg_plain(fvg_type, bool(fvg_active), fvg_bottom, fvg_top, tkr)
    rr_poor = finite_num(clean_float(rr_ratio, np.nan)) and clean_float(rr_ratio, np.nan) < 1.0
    is_recovery_or_buyish = any(
        word in str(dec or "")
        for word in ("회복", "눌림", "분할", "진입", "매수", "적립", "홀드")
    )

    lines = []

    # ── 0. 오늘 결론: 서로 다른 신호를 먼저 한 문장으로 정리 ────────────
    if is_recovery_or_buyish and rr_poor:
        lines.append(
            "<b>오늘 결론</b>: 종목의 회복/품질 신호는 살아 있지만, <b>현재가 기준 손익비가 낮아 바로 풀진입할 자리는 아닙니다.</b> "
            "보유자는 유지·속도조절, 신규/추매는 돌파 후 눌림이나 손절 기준이 가까워지는 구간을 기다립니다."
        )
    elif is_recovery_or_buyish:
        lines.append(
            "<b>오늘 결론</b>: 회복 후보로 볼 수 있지만, 실제 매수 강도는 가격위치·손익비·거래량 확인 뒤 정합니다."
        )
    elif "보류" in str(dec or "") or "차단" in str(dec or "") or "방어" in str(dec or ""):
        lines.append(
            "<b>오늘 결론</b>: 지금은 매수보다 원인 점검과 회복 조건 확인이 우선입니다."
        )
    else:
        lines.append(
            "<b>오늘 결론</b>: 방향이 완전히 정리되지 않았으므로 보조 신호보다 다음 봉 확인을 우선합니다."
        )

    # ── 1. 현재 판정 한 줄 ──────────────────────────────────
    fin_labels = {4: "💎완성형 우량(4/4)", 3: "✅양호(3/4)", 2: "🔶보통(2/4)", 1: "⚠️주의(1/4)", 0: "🚨위험(0/4)"}
    if is_etf is None:
        product_type = (c.get("execution_workflow") or {}).get("유형")
        if c.get("is_etf") is not None:
            is_etf = clean_bool(c["is_etf"])
        elif product_type in {"ETF", "개별주"}:
            is_etf = product_type == "ETF"
        else:
            is_etf = is_fin_score_exempt_asset(tkr, False, c.get("asset_class", ""), name)
    fin_desc = "해당없음(ETF/ETN 등)" if clean_bool(is_etf) else fin_labels.get(fin_score, f"{fin_score}점")
    lines.append(
        f"<b>📋 현재 판정</b>: <b>{dec}</b> &nbsp;|&nbsp; "
        f"후보등급 {grade} &nbsp;|&nbsp; 종합점수 {t_score}점 "
        f"(기술 {tech_total}점 / 재무 {fin_desc})"
    )

    # ── 2. 기술 구조 ─────────────────────────────────────────
    # 추세
    trend_interp = {
        "🚀정배열(상승)": "장기 정배열 상승 구조",
        "🌊역배열(하락)": "역배열 하락 구조",
        "➡️횡보/혼조": "횡보·혼조 구간",
        "🆕신규상장/자료부족": "상장 초기(MA 미형성)",
    }.get(trend, trend)

    # RSI
    if rsi >= 70:
        rsi_interp = f"RSI <b>{rsi:.0f}</b> — 단기 과열 구간, 조정·횡보 가능성 있음"
    elif rsi >= 60:
        rsi_interp = f"RSI <b>{rsi:.0f}</b> — 강세 유지 중"
    elif rsi >= 45:
        rsi_interp = f"RSI <b>{rsi:.0f}</b> — 눌림 구간, 진입 적합 범위"
    elif rsi >= 30:
        rsi_interp = f"RSI <b>{rsi:.0f}</b> — 약세·바닥 탐색 중"
    else:
        rsi_interp = f"RSI <b>{rsi:.0f}</b> — 극단적 과매도"

    # %B
    if not finite_num(pct_b):
        pb_interp = "%B 산출불가 — 볼린저 이력 확인 필요"
    elif pct_b > 1:
        pb_interp = f"%B <b>{pct_b:.2f}</b> — 볼린저 상단 초과, 단기 과열"
    elif pct_b >= 0.75:
        pb_interp = f"%B <b>{pct_b:.2f}</b> — 볼린저 상단 근접"
    elif pct_b >= 0.35:
        pb_interp = f"%B <b>{pct_b:.2f}</b> — 볼린저 중립 구간"
    else:
        pb_interp = f"%B <b>{pct_b:.2f}</b> — 볼린저 하단 근접, 과매도 구간"

    # MFI
    if not finite_num(mfi):
        mfi_interp = "MFI 산출불가 — 거래량 이력 확인 필요"
    elif mfi >= 80:
        mfi_interp = f"MFI <b>{mfi:.0f}</b> — 자금 유입 과열(익절 주의)"
    elif mfi >= 55:
        mfi_interp = f"MFI <b>{mfi:.0f}</b> — 자금 유입 우세"
    elif mfi >= 40:
        mfi_interp = f"MFI <b>{mfi:.0f}</b> — 자금 중립"
    else:
        mfi_interp = f"MFI <b>{mfi:.0f}</b> — 자금 유출 우세"
    quote_meta = c.get("live_quote", {})
    if quote_meta.get("volume_status") == "missing_live_volume":
        asof = str(quote_meta.get("mfi_asof") or "")[:10]
        mfi_interp += f" (가격만 갱신 · MFI 기준 {asof or '자료없음'} · 최신 수급 확인 불가)"

    # RS slope
    slope_desc = ""
    if rs_slope == "📈RS상승중":
        slope_desc = ", 상대강도 가속 중"
    elif rs_slope == "📉RS하락중":
        slope_desc = ", 상대강도 약화 중(추격 주의)"

    lines.append(
        f"🔧 <b>기술 구조</b>: {trend_interp}, RS {rs_label}{slope_desc}. "
        f"{rsi_interp}. {pb_interp}. {mfi_interp}. "
        f"MACD: <b>{macd}</b> / SQZ: <b>{sqz}</b>."
    )

    # ── 3. SMC 구조 ──────────────────────────────────────────
    smc_parts = [f"외부구조 <b>{ext_struct}</b> / 내부구조 <b>{int_struct}</b>"]
    if int_event and int_event not in ("None", "없음", ""):
        smc_parts.append(f"내부 이벤트: <b>{int_event}</b>")
    if ext_event and ext_event not in ("None", "없음", ""):
        smc_parts.append(f"외부 이벤트: <b>{ext_event}</b>")
    if fvg_type != "없음" and fvg_type:
        fvg_range = ""
        if fvg_bottom and fvg_top and fvg_bottom > 0:
            fvg_range = f" ({format_currency(fvg_bottom, tkr)}~{format_currency(fvg_top, tkr)})"
        smc_parts.append(f"FVG: <b>{escape_html_value(fvg_plain_label)}</b>{fvg_range}")
    smc_parts.append(f"현재 가격대: <b>{pd_zone}</b>")
    if is_52w:
        smc_parts.append("🚀 <b>52주 신고가 돌파</b>")
    lines.append("🛡️ <b>SMC 구조</b>: " + " | ".join(smc_parts))
    if fvg_type != "없음" and fvg_type:
        lines.append(f"&nbsp;&nbsp;&nbsp;&nbsp;→ FVG 해석: {escape_html_value(fvg_plain_note)}")
    if smc_insight:
        lines.append(f"&nbsp;&nbsp;&nbsp;&nbsp;→ {smc_insight}")
    if smc_action:
        lines.append(f"&nbsp;&nbsp;&nbsp;&nbsp;🎯 실행 해석: <b>{smc_action}</b>")

    # ── 4. 수급·가격 흐름 ────────────────────────────────────
    flow_parts = [f"섹터 머니플로우: <b>{sector_flow}</b>"]
    if c.get("live_price_used") and finite_num(regular_day_ret):
        reg_emoji = "🔺" if regular_day_ret > 0 else "🔻"
        flow_parts.append(f"정규장 전일등락: {reg_emoji} <b>{regular_day_ret*100:.1f}%</b>")
        if finite_num(live_ref_ret) and abs(live_ref_ret) > 0.003:
            live_emoji = "🔺" if live_ref_ret > 0 else "🔻"
            flow_parts.append(f"최신가-종가: {live_emoji} <b>{live_ref_ret*100:.1f}%</b>")
    elif day_ret != 0:
        dr_emoji = "🔺" if day_ret > 0 else "🔻"
        flow_parts.append(f"{day_ret_label}: {dr_emoji} <b>{day_ret*100:.1f}%</b>")
    if finite_num(vol_ratio) and vol_ratio > 0:
        vol_desc = "거래량 급증" if vol_ratio >= 2 else ("보통" if vol_ratio >= 0.7 else "거래량 감소")
        volume_detail = ""
        if finite_num(last_volume) and finite_num(vol_ma20) and vol_ma20 > 0:
            volume_detail = f" · {last_volume:,.0f}주 vs 기준 {vol_ma20:,.0f}주"
            if vol_valid_count and vol_valid_count < 20:
                volume_detail += f"({vol_valid_count}일)"
        flow_parts.append(f"거래량 기준비: <b>{vol_ratio:.1f}x</b> ({vol_desc}{volume_detail})")
    elif finite_num(last_volume) and last_volume > 0:
        flow_parts.append(f"거래량: <b>{last_volume:,.0f}주</b> (비교 기준 부족)")
    if ma5 > 0 and ma20 > 0 and cur_p > 0:
        pos_vs_ma5 = (cur_p / ma5 - 1) * 100
        pos_vs_ma20 = (cur_p / ma20 - 1) * 100
        flow_parts.append(f"MA5 대비 {pos_vs_ma5:+.1f}% / MA20 대비 {pos_vs_ma20:+.1f}%")
    lines.append("💸 <b>수급·가격 흐름</b>: " + " | ".join(flow_parts))

    sideways_state = build_sideways_quality_state(
        c,
        is_leveraged_product=bool(c.get("is_leveraged_or_inverse")) or is_leveraged_or_inverse_product(
            name, tkr, str(c.get("asset_class", "") or "")
        ),
        has_pos=has_p,
    )
    if sideways_state:
        reason_text = sideways_state.get("reason_text", "")
        reason_html = f" <span style='color:#94a3b8;'>({escape_html_value(reason_text)})</span>" if reason_text else ""
        lines.append(
            f"🧭 <b>횡보/눌림 품질</b>: <b>{escape_html_value(sideways_state.get('label', '-'))}</b> — "
            f"{escape_html_value(sideways_state.get('note', ''))}{reason_html}"
        )

    signal_roles = []
    if is_recovery_or_buyish:
        signal_roles.append("회복 후보 = 종목의 품질·상대강도·추세 회복을 좋게 본다는 뜻")
    if rr_poor:
        signal_roles.append("손익비 불리 = 현재가에서 목표 대비 손절폭이 커서 실행 강도를 낮추라는 뜻")
    if fvg_type == "Bullish FVG" and fvg_active:
        signal_roles.append("상승 FVG = 아래 지지 후보가 남아 있다는 뜻, 지지 확인 전에는 보조 근거")
    elif fvg_type == "Bearish FVG" and fvg_active:
        signal_roles.append("하락 FVG = 위 저항 후보가 남아 있다는 뜻, 돌파 확인 전에는 부담 요인")
    if smc_action and "관망" in smc_action:
        signal_roles.append("SMC 관망 = 구조가 아직 한 방향으로 확정되지 않았다는 뜻")
    if signal_roles:
        lines.append("🧩 <b>신호 정리</b>: " + " / ".join(signal_roles))

    # ── 5. 진입 조건 (핵심: 뭐가 부족한지) ──────────────────
    entry_hint = ""
    if decision_code == "S_UPTREND_WAIT_PULLBACK":
        missing = []
        if rsi > 65:
            missing.append(f"RSI {rsi:.0f} → <b>65 이하</b>")
        if pct_b > 0.75:
            missing.append(f"%B {pct_b:.2f} → <b>0.75 이하</b>")
        if mfi >= 75:
            missing.append(f"MFI {mfi:.0f} → <b>75 미만</b>")
        if missing:
            entry_hint = (
                f"⏳ <b>진입 전환 조건</b>: {', '.join(missing)} 충족 시 "
                f"<b>'우량주 눌림 구간: 정찰 진입 적합'</b>으로 신호 전환됩니다. "
                f"급락 없이도 며칠 <b>횡보·숨 고르기</b>만으로 충족될 수 있습니다."
            )
    elif decision_code == "A_UPTREND_WAIT_PULLBACK":
        missing = []
        if rsi > 65: missing.append(f"RSI {rsi:.0f} → <b>65 이하</b>")
        if pct_b > 0.75: missing.append(f"%B {pct_b:.2f} → <b>0.75 이하</b>")
        if missing:
            entry_hint = f"⏳ <b>진입 전환 조건 (A급)</b>: {', '.join(missing)} 충족 필요."
    elif decision_code in ("QUALITY_PULLBACK_ENTRY", "TREND_PULLBACK_EXPLORE"):
        entry_hint = "✅ <b>현재 진입 구간</b>: 눌림 매수 적합 시점입니다."
    elif decision_code == "CORE_ETF_DCA_BUY":
        entry_hint = "✅ <b>코어 ETF 분할매수</b> 적합 구간입니다."
    elif decision_code in ("REVERSE_TREND_NO_ENTRY", "STRONG_REVERSE_NO_ENTRY"):
        entry_hint = "🚫 <b>진입 보류</b>: 역배열·하락 구조. 추세 전환 확인 전까지 신규 진입은 위험합니다."
    elif decision_code == "PROFIT_TAKE_SIGNAL":
        entry_hint = "💰 <b>익절 신호</b>: MFI·%B 과열 + 평단 대비 수익 20% 이상. 일부 익절 고려."
    elif decision_code == "HOLD_QUALITY_UPTREND":
        entry_hint = "🏆 <b>홀드 구간</b>: 정배열 유지 중이나 추매보다 홀드가 우선인 타이밍."
    elif decision_code in ("LEADER_MA5_PULLBACK_ENTRY", "LEADER_MA5_FAST_PULLBACK_ENTRY",
                           "OVERHEAT_EXTENSION_WAIT_MA5"):
        _ma5_str = format_currency(ma5, tkr) if ma5 > 0 else "MA5"
        _curr_w  = c.get("current_w", 0.0)
        _targ_w  = c.get("target_w",  0.0)
        if has_p and _targ_w > 0 and _curr_w < _targ_w * 0.97:
            # 기존 보유 + 비중 부족 → "MA5 눌림 시 추가" 안내
            entry_hint = (
                f"⏳ <b>추매 대기 — MA5 눌림 확인 후 추가</b>: "
                f"볼린저 상단권(%B {pct_b:.2f})이라 지금 바로 추매는 불리합니다. "
                f"{_ma5_str} 근처로 조정 시 현재 비중 부족분 "
                f"(<b>{_curr_w:.1f}% → 목표 {_targ_w:.1f}%</b>) 일부 분할 추가를 검토하세요. "
                f"별도 급락 없이 며칠 <b>횡보·숨 고르기</b>만으로도 %B가 내려올 수 있습니다."
            )
        elif has_p:
            # 기존 보유 + 비중 충족·초과 → 홀드
            entry_hint = (
                f"🏆 <b>홀드 — MA5 눌림까지 관망</b>: "
                f"볼린저 상단권(%B {pct_b:.2f}). "
                f"비중이 충족된 상태이므로 추매보다 홀드 유지가 우선입니다. "
                f"{_ma5_str} 눌림 후 재평가하세요."
            )
        else:
            # 미보유 → 신규 진입 대기
            entry_hint = (
                f"⏳ <b>진입 대기 — MA5 눌림 확인 후 정찰</b>: "
                f"볼린저 상단권(%B {pct_b:.2f}) 추격 진입은 위험합니다. "
                f"{_ma5_str} 근처로 조정 시 목표비중의 1/3 소량 정찰 진입을 검토하세요."
            )

    if entry_hint:
        lines.append(entry_hint)

    # ── 6. R/R ───────────────────────────────────────────────
    if rr_ratio and rr_ratio > 0 and rr_target and rr_stop:
        if rr_target_is_projection:
            lines.append(
                f"📐 <b>R/R 비율</b>: <b>{rr_ratio:.2f}</b> — "
                f"강세 시나리오 상단 {format_currency(rr_target, tkr)} / 손절 {format_currency(rr_stop, tkr)}"
            )
            lines.append(
                f"    → 위 가격은 확정 목표가가 아니라 {escape_html_value(rr_target_source)}입니다. "
                "신고가 구간은 1~2ATR 분할익절 후 잔여 추적손절이 우선입니다."
            )
        else:
            lines.append(
                f"📐 <b>R/R 비율</b>: <b>{rr_ratio:.2f}</b> — "
                f"목표가 {format_currency(rr_target, tkr)} / 손절 {format_currency(rr_stop, tkr)}"
            )

    # ── 7. 내 포지션 손익 ─────────────────────────────────────
    if has_p and my_p > 0 and cur_p > 0:
        pnl_pct = (cur_p / my_p - 1) * 100
        pnl_emoji = "📈" if pnl_pct >= 0 else "📉"
        lines.append(
            f"{pnl_emoji} <b>내 손익</b>: 평단 {format_currency(my_p, tkr)} 대비 현재가 {pnl_pct:+.1f}%"
        )

    border_color = "#10b981" if "진입" in dec or "매수" in dec or "홀드" in dec else (
        "#ef4444" if "보류" in dec or "역배열" in dec else "#6366f1"
    )
    lines, border_color = align_precision_narrative_display(
        lines, border_color, c.get("execution_workflow"), entry_hint=entry_hint, decision_code=decision_code,
    )
    html = (
        f"<div class='info-panel' style='border-left:5px solid {border_color}; line-height:2.0;'>"
        f"<b>📖 종합 해설</b><br><br>"
        + "<br>".join(f"• {line}" for line in lines)
        + "</div>"
    )
    return html
