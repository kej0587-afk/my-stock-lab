"""Pure holdings interpretation for the Today briefing; no fetching or orders.

Inputs are the exact saved result, current holdings metadata and existing masks.
Returned prose is explanatory; the operational gate remains in the row.
"""
import re
import numpy as np
import pandas as pd

from stock_lab_core.formatters import clean_float, finite_num, normalize_ticker, sanitize_ticker_value
from stock_lab_core.asset_classifier import is_leveraged_or_inverse_product


def build_briefing_asset_interpretation(df, held_meta, watch_items, *, hard_block_mask,
                                        caution_mask, context_ok, market_defensive, safe_float):
    def _mask_at(mask, idx) -> bool:
        try:
            if isinstance(mask, pd.Series):
                return bool(mask.reindex(df.index, fill_value=False).loc[idx])
        except Exception:
            return False
        return False

    watch_meta = {
        normalize_ticker(sanitize_ticker_value(item.get("ticker", ""))): item
        for item in (watch_items or [])
        if isinstance(item, dict)
    }
    review_lines: list[str] = []
    core_hold_lines: list[str] = []
    keep_lines: list[str] = []
    no_add_lines: list[str] = []
    unknown_lines: list[str] = []
    asset_interpretation_rows: list[dict] = []

    if not df.empty and held_meta:
        ticker_source = df.get("티커", pd.Series("", index=df.index))
        for idx, row in df.iterrows():
            ticker = normalize_ticker(sanitize_ticker_value(ticker_source.loc[idx] if idx in ticker_source.index else row.get("티커", "")))
            meta = held_meta.get(ticker)
            if not meta:
                continue

            name = str(row.get("종목명", row.get("자산명", ticker)) or ticker).strip()
            label = str(row.get("🔥기술적 타점", "") or "")
            final_read = str(row.get("최종읽기", "") or "")
            code = str(row.get("판정코드", "") or "")
            item = watch_meta.get(ticker, {})
            bucket = str(item.get("bucket", row.get("bucket", row.get("버킷", ""))) or "").lower()
            asset_class = str(item.get("asset_class", row.get("유형", "")) or "").lower()
            ticker_upper = ticker.upper()
            name_key = name.lower()
            current_price = safe_float(row.get("현재가", np.nan), np.nan)
            avg_price = clean_float(meta.get("매입가"), np.nan)
            pnl = np.nan
            for pnl_col in ["내손익률", "손익률", "평단대비", "수익률"]:
                if pnl_col in row.index:
                    pnl = safe_float(row.get(pnl_col), np.nan)
                    if finite_num(pnl):
                        break
            if not finite_num(pnl) and finite_num(current_price) and finite_num(avg_price) and avg_price > 0:
                pnl = (float(current_price) / float(avg_price) - 1.0) * 100.0

            current_w = clean_float(meta.get("현재비중"), np.nan)
            target_w = clean_float(meta.get("목표비중"), np.nan)
            gap_w = clean_float(meta.get("비중차이"), np.nan)
            if not finite_num(gap_w) and finite_num(current_w) and finite_num(target_w):
                gap_w = target_w - current_w

            is_hard = _mask_at(hard_block_mask, idx) or "HARD_BLOCK" in code or "하드차단" in label
            is_caution = _mask_at(caution_mask, idx)
            is_overweight = finite_num(gap_w) and float(gap_w) < -0.2
            is_underweight = finite_num(gap_w) and float(gap_w) > 0.2
            is_leverage = (
                bucket == "leverage"
                or bool(re.search(r"QLD|TQQQ|SOXL|BITX|BITU|UPRO|SSO|TECL|FNGU|2X|3X|레버리지|Ultra", ticker_upper + " " + name, re.I))
            )
            is_sector_or_tactical = bool(re.search(
                r"반도체|Top2|DRAM|Bitcoin|비트코인|원자재|구리|FCX|Freeport|프리포트|TDF|2045|섹터|테마",
                ticker_upper + " " + name + " " + asset_class,
                re.I,
            ))
            is_core = (
                (bucket == "core" or ticker_upper in {"379800", "379810", "VOO", "SPY", "IVV", "QQQ", "QQQM"})
                and not is_leverage
                and not is_sector_or_tactical
            ) or (
                not is_leverage
                and not is_sector_or_tactical
                and any(k in name_key for k in ["s&p500", "s&p 500", "sp500", "나스닥100", "nasdaq100", "nasdaq 100"])
            )
            damaged_label = any(k in (label + final_read) for k in [
                "구조훼손", "추세훼손", "시장방어", "가격방어", "급락방어", "추세방어",
                "추매금지", "추매중단", "비중 초과", "하드차단", "보유점검",
            ])
            pnl_text = "-" if not finite_num(pnl) else f"{float(pnl):+.1f}%"
            weight_text = ""
            if finite_num(current_w) or finite_num(target_w):
                cw = "-" if not finite_num(current_w) else f"{float(current_w):.1f}%"
                tw = "-" if not finite_num(target_w) else f"{float(target_w):.1f}%"
                weight_text = f" · 비중 {cw}/{tw}"
            base_line = f"{name}({ticker}) 손익 {pnl_text}{weight_text}"

            def _weight_cell(value):
                return "-" if not finite_num(value) else f"{float(value):.1f}%"

            def _add_asset_interpretation(bucket_label: str, action: str, target_lines: list[str]):
                from stock_lab_core.report_evidence import holding_reasons
                from stock_lab_core.today_overview import action_columns
                reasons = holding_reasons(dict(row, 현재비중=current_w, 목표비중=target_w))
                if is_leveraged_or_inverse_product(name, ticker, asset_class):
                    reasons.append("레버리지 보유")
                target_lines.append(base_line + " → " + action)
                asset_interpretation_rows.append({
                    "구분": bucket_label,
                    "자산": name,
                    "티커": ticker,
                    **action_columns(row),
                    "판정·자산 대조": "계산 입력 일치" if context_ok else "입력 변경/미확인 · 이전 판정",
                    "손익": pnl_text,
                    "현재비중": _weight_cell(current_w),
                    "목표비중": _weight_cell(target_w),
                    "비중차이": _weight_cell(gap_w),
                    "보유 점검 사유": ", ".join(dict.fromkeys(reasons)),
                    "보유분 관리": action,
                })

            if is_core:
                if is_overweight:
                    _add_asset_interpretation("장기코어 유지/속도조절", "장기코어 유지, 목표초과라 신규매수 중단/리밸런싱", core_hold_lines)
                elif market_defensive or is_caution or damaged_label:
                    _add_asset_interpretation("장기코어 유지/속도조절", "장기코어 교체 아님, 시장 안정 후 정해진 적립 재개", core_hold_lines)
                elif is_underweight:
                    _add_asset_interpretation("비중대로 가능 또는 보유 유지", "장기코어 목표비중 안에서 분할 적립 가능", keep_lines)
                else:
                    _add_asset_interpretation("장기코어 유지/속도조절", "장기코어 보유 유지", core_hold_lines)
            elif is_leverage and (is_hard or damaged_label or (finite_num(pnl) and float(pnl) <= -10)):
                _add_asset_interpretation("종목변경/비중축소 검토", "비중대로 밀기보다 원인점검/교체 후보 검토", review_lines)
            elif is_hard or (damaged_label and finite_num(pnl) and float(pnl) <= -15):
                _add_asset_interpretation("종목변경/비중축소 검토", "위성/개별 비중 축소 또는 대체 후보 검토", review_lines)
            elif is_caution or damaged_label or is_overweight:
                _add_asset_interpretation("추가매수 제외/조건 확인", "추가매수 제외, 회복 조건 확인", no_add_lines)
            elif is_underweight and not is_caution:
                _add_asset_interpretation("비중대로 가능 또는 보유 유지", "목표비중 안에서 분할 적립 가능", keep_lines)
            elif finite_num(pnl):
                _add_asset_interpretation("비중대로 가능 또는 보유 유지", "보유 유지 중심", keep_lines)
            else:
                _add_asset_interpretation("데이터 확인 필요", "평단/현재가 확인 필요", unknown_lines)

    return (review_lines, core_hold_lines, keep_lines, no_add_lines, unknown_lines, asset_interpretation_rows)


from stock_lab_core.report_build import register_loaded_source
register_loaded_source(__name__, __file__)
