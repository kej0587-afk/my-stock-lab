"""Compact report-only comparison of distinct history baselines."""

from stock_lab_core.report_build import register_loaded_source
from stock_lab_core.report_evidence import KST, _cell, first, holding_reasons, is_held, records, stamp, text

register_loaded_source(__name__, __file__)


def _label(row, fallback=None):
    ticker = text(first(row, "티커", "ticker"))
    name = text(first(row, "종목명", "name", "자산명"))
    if not name or name == ticker:
        name = text(first(fallback or {}, "종목명", "name", "자산명"))
    return f"{name}({ticker})" if name and name != ticker else f"{ticker}(종목명 미저장)"


def _reasons(row):
    value = row.get("저장사유", holding_reasons(row))
    values = value if isinstance(value, (list, tuple)) else [value]
    return tuple(sorted({text(item) for item in values if text(item)}))


def _date_pair(value):
    parts = text(value).split("/")
    return f"미국 {parts[0]} / 한국 {parts[1]}" if len(parts) == 2 else text(value)


def _table(headers, rows):
    return [" | ".join(headers), " | ".join("---" for _ in headers),
            *(" | ".join(_cell(value) for value in row) for row in rows), ""]


def history_comparison_lines(current, baselines):
    """Deduplicate identical transitions, retaining every baseline's own counts."""
    current_rows = records(current)
    current_map = {text(first(row, "티커", "ticker")): row for row in current_rows
                   if text(first(row, "티커", "ticker"))}
    summary, changes, membership, notes = [], {}, {}, []
    for baseline in baselines:
        previous_date, current_date = text(baseline.get("previous_date")), text(baseline.get("current_date"))
        same = baseline.get("same_session", False)
        valid = previous_date == current_date if same else previous_date < current_date
        if not previous_date or not current_date or not valid:
            notes.append("같은 거래일 비교 없음: 직전 생성 이력이 없습니다." if same else
                         "전일 비교 없음: 이전 거래일의 저장된 점검이 없습니다.")
            continue
        reference = "같은 거래일 직전 생성" if same else "이전 거래일"
        at = stamp(baseline.get("previous_run_at")) if same else None
        basis = at.astimezone(KST).strftime("%Y-%m-%d %H:%M KST") if at else _date_pair(previous_date)
        old = {text(first(row, "티커", "ticker")): row for row in records(baseline.get("previous"))
               if text(first(row, "티커", "ticker"))}
        compared, changed = {False: 0, True: 0}, {False: 0, True: 0}
        for ticker, row in current_map.items():
            if ticker not in old:
                continue
            prior = old[ticker]
            before = text(first(prior, "최종읽기", "🔥기술적 타점", "판정코드"))
            after = text(first(row, "최종읽기", "🔥기술적 타점", "판정코드"))
            if not before or not after:
                continue
            held = is_held(row)
            compared[held] += 1
            fields = []
            old_gate, new_gate = (text(first(item, "게이트상태", "gate_state")) for item in (prior, row))
            gate_in_verdict = bool(old_gate and new_gate and before.startswith(old_gate) and after.startswith(new_gate))
            if before != after:
                fields.append(("판정·게이트" if old_gate != new_gate and gate_in_verdict else "판정", before, after))
            if old_gate != new_gate and not (before != after and gate_in_verdict):
                fields.append(("게이트", old_gate or "미제공", new_gate or "미제공"))
            old_reasons, new_reasons = _reasons(prior), _reasons(row)
            if old_reasons != new_reasons:
                fields.append(("사유", ", ".join(old_reasons), ", ".join(new_reasons)))
            changed[held] += bool(fields)
            for field, old_value, new_value in fields:
                key = (ticker, held, field, old_value, new_value)
                change = changes.setdefault(key, {"label": _label(row, prior), "references": []})
                if reference not in change["references"]:
                    change["references"].append(reference)
        for held, label in ((True, "보유"), (False, "관심·미보유")):
            total = sum(is_held(row) == held for row in current_rows)
            summary.append((reference, basis, f"{label} {total}개", compared[held], total - compared[held],
                            f"{changed[held]}개" if compared[held] else "비교 불가"))
        for action, tickers, source in (("추가", sorted(current_map.keys() - old.keys()), current_map),
                                         ("이탈", sorted(old.keys() - current_map.keys()), old)):
            for ticker in tickers:
                item = membership.setdefault((action, ticker), {"label": _label(source[ticker]), "references": []})
                if reference not in item["references"]:
                    item["references"].append(reference)
    lines = []
    if summary:
        lines += _table(("비교 기준", "이전 기준일·시각", "대상", "비교", "미비교", "변경"), summary)
    if changes:
        lines.append("**판정·사유 변화**")
        lines += _table(("종목", "변경 항목", "이전", "현재", "비교 기준"), [
            (value["label"], key[2], key[3], key[4], " · ".join(value["references"])) for key, value in changes.items()])
    elif summary:
        lines.append("공통 종목의 판정·게이트·사유 변경 없음." if any(row[3] for row in summary) else
                     "비교 가능한 공통 종목 판정 없음.")
    if membership:
        lines.extend(["", "**점검 입력 목록 변화**"])
        lines += _table(("구분", "종목", "비교 기준"), [
            (key[0], value["label"], " · ".join(value["references"])) for key, value in membership.items()])
        lines.append("입력 목록의 차이이며 관심등록 삭제 여부는 미확인입니다. 보고서 상위 10개 변화가 아닌 입력 목록 차이입니다.")
    lines.extend(dict.fromkeys(notes))
    return lines
