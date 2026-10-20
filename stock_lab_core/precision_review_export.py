"""Serialize already-rendered precision results. No fetching or trading logic."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timezone
from decimal import Decimal
import io
import json
import math
import re
from urllib.parse import urlsplit, urlunsplit
import zipfile

import numpy as np
import pandas as pd

from stock_lab_core.backup import build_review_export_zip
from stock_lab_core.formatters import clean_float


EXPORT_VERSION = "1.1"
REVIEW_NOTICE = "review not trading change"
_READY_KEY = "_precision_review_export_ready"
_REQUIRED_SECTIONS = {
    "main_decision", "execution_workflow", "multi_timeframe", "final_check",
    "valuation", "financial_inputs", "entry_plan", "hold_or_cut", "signal_evidence", "context",
}
_IDENTITY_KEYS = ("ticker", "tkr", "symbol", "티커")
_PRIVATE_KEY = re.compile(
    r"secret|password|credential|token|api.?key|authorization|cookie|session|"
    r"account|email|owner|user.?(?:id|name)|current.?user|service.?role|private.?key|"
    r"^(?:id|uid|user|auth|login|settings|holdings|watchlist|portfolio)$|"
    r"계좌|이메일|사용자|소유자", re.I,
)
_EMAIL = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
_URL = re.compile(r"https?://[^\s<>\"']+")
_FINANCIAL_KEYS = {
    "ticker", "auto_score", "manual_score", "final_score", "source", "mode",
    "notes", "metrics", "updated_at", "asof", "score",
}
_CONTEXT_KEYS = {
    "name", "is_etf", "asset_class", "has_position", "my_price", "usdkrw",
    "app_mode", "displayed_price", "auto_price", "manual_price", "price_source",
    "price_refresh_time", "chart_load_note", "live_ohlcv_applied",
    "macro_risk", "macro_penalty",
}
_CANDIDATE_KEYS = (
    "grade", "t_score", "tech_total", "fin_score", "adj", "rs_s", "mfi_s",
    "trend_s", "macd_s", "sqz_s", "rs_slope_s", "rs_slope_label",
)


def _mapping(value):
    return value if isinstance(value, Mapping) else {}


def _text(value):
    return value.strip() if isinstance(value, str) else ""


def _ticker(value):
    # Do not collapse .KS/.KQ or other distinct listings into the same security.
    return _text(value).upper()


def _check_identity(value, ticker):
    def check(item):
        if item is None or item is pd.NA or item is pd.NaT:
            return
        if isinstance(item, (float, np.floating)) and math.isnan(item):
            return
        if not isinstance(item, str) or (_ticker(item) and _ticker(item) != ticker):
            raise ValueError("Review snapshot ticker mismatch")

    if isinstance(value, pd.DataFrame):
        _check_identity(value.attrs, ticker)
        _check_identity(value.attrs.get("live_quote"), ticker)
        for key in _IDENTITY_KEYS:
            if key in value.columns:
                for item in value[key].to_numpy().flat:
                    check(item)
    else:
        for key in _IDENTITY_KEYS:
            check(_mapping(value).get(key))


def _public_text(value):
    def public_url(match):
        try:
            url = urlsplit(match.group())
            return urlunsplit((url.scheme, url.netloc.rsplit("@", 1)[-1], url.path, "", ""))
        except ValueError:
            return "[redacted URL]"
    return _EMAIL.sub("[redacted email]", _URL.sub(public_url, value))


def _json_value(value, seen=None, depth=0):
    """Copy known value types only; never stringify arbitrary runtime objects."""
    if value is None or value is pd.NA or value is pd.NaT or depth > 24:
        return None
    if isinstance(value, str):
        # Some persisted financial inputs contain JSON encoded inside a cell.
        if value.lstrip().startswith(("{", "[")):
            try:
                return _json_value(json.loads(value), seen, depth + 1)
            except (ValueError, RecursionError):
                pass
        return _public_text(value)
    if isinstance(value, (bool, int)):
        return value
    if isinstance(value, (float, Decimal)):
        return float(value) if math.isfinite(value) else None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, np.generic):
        return _json_value(value.item(), seen, depth + 1)
    seen = set() if seen is None else seen
    if id(value) in seen:
        return None
    seen = seen | {id(value)}
    if isinstance(value, pd.DataFrame):
        positions = [i for i, col in enumerate(value.columns) if not _PRIVATE_KEY.search(str(col))]
        return {
            "columns": [_json_value(value.columns[i], seen, depth + 1) for i in positions],
            "index": [_json_value(item, seen, depth + 1) for item in value.index],
            "rows": [
                [_json_value(row[i], seen, depth + 1) for i in positions]
                for row in value.itertuples(index=False, name=None)
            ],
        }
    if isinstance(value, pd.Series):
        return _json_value(value.to_dict(), seen, depth + 1)
    if isinstance(value, np.ndarray):
        return _json_value(value.tolist(), seen, depth + 1)
    if isinstance(value, Mapping):
        return {
            _public_text(str(key)): _json_value(item, seen, depth + 1)
            for key, item in value.items()
            if isinstance(key, (str, int)) and not _PRIVATE_KEY.search(str(key))
        }
    if isinstance(value, (list, tuple)):
        return [_json_value(item, seen, depth + 1) for item in value]
    return None


def _csv_cell(value):
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False, allow_nan=False)
    if isinstance(value, str) and (
        value.lstrip().startswith(("=", "+", "-", "@"))
        or value.startswith(("\t", "\r", "\n"))
    ):
        return "'" + value
    return value


def _csv_safe(frame):
    out = frame.map(_csv_cell)
    out.columns = [_csv_cell(str(col)) for col in out.columns]
    return out


def _flatten(value, path=""):
    if isinstance(value, dict) and value:
        for key, item in value.items():
            yield from _flatten(item, f"{path}.{key}" if path else key)
    elif isinstance(value, list) and value:
        for index, item in enumerate(value):
            yield from _flatten(item, f"{path}[{index}]")
    else:
        yield {"field": path or "value", "value": value}


def _stance(label):
    """Review-only wording contrast, not an execution gate or recommendation."""
    label = _text(label)
    if not label:
        return "unknown"
    if any(word in label for word in (
        "금지", "차단", "보류", "대기", "관망", "관찰", "방어", "데이터확인",
        "확인 후", "확인후", "조건부", "눌림 진입",
    )):
        return "restricted"
    if any(word in label for word in (
        "실행가능", "분할 가능", "분할 진입 가능", "타점 가능", "소액 분할",
        "1차 소액만", "매수 가능", "진입 가능", "승인", "정찰만", "시작 가능",
        "현재가 부근 1차 정찰", "현재가 부근 소액만",
    )):
        return "actionable_wording"
    return "unknown"


def _conflict_flags(sections):
    decision = _mapping(sections["main_decision"])
    workflow = _mapping(sections["execution_workflow"])
    final_check = _mapping(sections["final_check"])
    summary = _mapping(final_check.get("summary"))
    entry = _mapping(sections["entry_plan"])
    holding = _mapping(sections["hold_or_cut"])
    labels = {
        "main_decision": decision.get("dec"),
        "execution_gate": workflow.get("게이트상태"),
        "final_check": summary.get("final_label"),
        "entry_plan": entry.get("status"),
    }
    flags = []

    def add(code, left, right, note):
        flags.append({
            "code": code, "left": left, "right": right,
            "note": note, "scope": REVIEW_NOTICE,
        })

    for left, right in (
        ("main_decision", "final_check"), ("execution_gate", "final_check"),
        ("entry_plan", "final_check"), ("main_decision", "execution_gate"),
    ):
        if {_stance(labels[left]), _stance(labels[right])} == {"restricted", "actionable_wording"}:
            add(f"{left}_vs_{right}", labels[left], labels[right], "Displayed wording differs; inspect original evidence.")
    grade = _text(decision.get("grade"))
    if ("S급" in grade or "A급" in grade or grade in {"S", "A"}) and _stance(labels["execution_gate"]) == "restricted":
        add("candidate_quality_vs_gate", grade, labels["execution_gate"], "Candidate quality is not entry permission; this contrast may be intentional.")
    if labels["main_decision"] and labels["final_check"] and labels["main_decision"] != labels["final_check"]:
        add("different_conclusion_labels", labels["main_decision"], labels["final_check"], "Different labels alone do not establish a trading-logic defect.")
    if _stance(labels["execution_gate"]) == "restricted":
        for section_name, section, text_key in (
            ("final_check", final_check, "해석"), ("entry_plan", entry, "조건"),
        ):
            rows = section.get("rows")
            for index, row in enumerate(rows if isinstance(rows, list) else []):
                detail = _mapping(row).get(text_key)
                if _stance(detail) == "actionable_wording":
                    add(
                        f"{section_name}_row_vs_execution_gate", detail, labels["execution_gate"],
                        f"{section_name}.rows[{index}].{text_key} permits entry while execution_workflow.게이트상태 is restricted. "
                        f"Gate reason: {_text(workflow.get('게이트근거'))}",
                    )
    entry_rows = entry.get("rows")
    entry_rows = entry_rows if isinstance(entry_rows, list) else []
    final_exit_prices = {
        _text(_mapping(row).get("가격")) for row in entry_rows
        if _mapping(row).get("단계") == "최종 익절"
    } - {""}
    if clean_float(entry.get("rr_now"), math.nan) < 1.0:
        for index, row in enumerate(entry_rows):
            row = _mapping(row)
            if (row.get("단계") == "1차 익절" and "1R 도달" in _text(row.get("조건"))
                    and _text(row.get("가격")) in final_exit_prices):
                add(
                    "entry_plan_take_profit_below_1r", row.get("조건"), row.get("가격"),
                    f"entry_plan.rows[{index}].가격 equals the final structure target, "
                    f"but entry_plan.rr_now={entry.get('rr_now')} is below 1R.",
                )
    holding_label = _text(holding.get("decision"))
    if holding_label and labels["final_check"]:
        add("holding_vs_entry_scope", holding_label, labels["final_check"], "Holding management and new entry have different scopes; compare their original reasons.")
        if "추가 확대도 검토 가능" in _text(holding.get("action")) and _stance(labels["final_check"]) == "restricted":
            add("holding_addition_vs_final_check", holding.get("action"), labels["final_check"], "Holding panel mentions additional exposure while final entry wording is restricted.")
        if any(word in holding_label for word in ("손절", "비중 축소")) and _stance(labels["final_check"]) == "actionable_wording":
            add("holding_defense_vs_final_check", holding_label, labels["final_check"], "Holding defense wording differs from final entry wording.")
    return flags


def _source_build(value):
    """Keep build identifiers/hashes, never local paths containing user names."""
    value = _mapping(value)
    if not value:
        return None
    result = {key: value.get(key) for key in (
        "base_commit", "loaded_source_sha256", "restart_required", "stale_modules",
    )}
    result["sources"] = {
        name: {key: _mapping(row).get(key) for key in ("sha256", "disk_sha256")}
        for name, row in _mapping(value.get("sources")).items()
    }
    return result


def _review_asof(histories):
    for frame in histories.values():
        if frame.empty:
            continue
        value = frame.index[-1]
        if isinstance(value, (datetime, date, np.datetime64)) and not pd.isna(value):
            return pd.Timestamp(value).isoformat()
        if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:[ T].*)?", value):
            try:
                return pd.Timestamp(value).isoformat()
            except ValueError:
                pass
    return None


def build_precision_review_export_zip(
    *, selected_ticker, result_ticker, decision=None, workflow_display=None,
    final_check=None, valuation=None, financial=None, entry_plan=None,
    signal_evidence=None, multi_timeframe=None, ohlcv=None, context=None,
    hold_or_cut=None, source_build=None, captured_at=None, source="precision",
    completion=None, stage="rendered",
):
    """Build an in-memory review ZIP from this render's explicitly supplied values.

    result_ticker is the identity of the calculation that produced decision.
    Callers must not relabel a cached result with a newly selected ticker.
    Embedded primary identities are checked as an additional stale-result guard.
    """
    ticker = _ticker(selected_ticker)
    if not re.fullmatch(r"[A-Z0-9^][A-Z0-9.^=_-]{0,39}", ticker) or ticker != _ticker(result_ticker):
        raise ValueError("Review snapshot ticker mismatch or missing ticker")
    if completion not in (None, "partial", "complete"):
        raise ValueError("Unknown review completion status")
    decision = _mapping(decision)
    workflow = _mapping(decision.get("execution_workflow"))
    for section in (
        decision, workflow, workflow_display, decision.get("live_quote"),
        final_check, valuation, financial, entry_plan, hold_or_cut, signal_evidence, context,
    ):
        _check_identity(section, ticker)
    for key in ("financial_inputs", "inputs"):
        _check_identity(_mapping(valuation).get(key), ticker)

    captured = captured_at or datetime.now(timezone.utc)
    if not isinstance(captured, datetime) or captured.tzinfo is None or captured.utcoffset() is None:
        raise ValueError("Review timestamp must include a timezone")

    frames = {}
    histories = {}
    for label, frame in _mapping(ohlcv).items():
        if isinstance(frame, pd.DataFrame):
            histories[str(label)] = frame
    timeframes = {}
    for label, pack in _mapping(multi_timeframe).items():
        _check_identity(pack, ticker)
        pack = _mapping(pack)
        _check_identity(pack.get("snapshot"), ticker)
        timeframes[str(label)] = {key: value for key, value in pack.items() if key != "df"}
        if isinstance(pack.get("df"), pd.DataFrame):
            histories[f"timeframe_{label}"] = pack["df"]

    sections = _json_value({
        "candidate_grade": {key: decision.get(key) for key in _CANDIDATE_KEYS},
        "main_decision": {key: value for key, value in decision.items() if key != "execution_workflow"},
        "execution_workflow": workflow,
        "workflow_display": workflow_display,
        "multi_timeframe": timeframes,
        "final_check": final_check,
        "valuation": valuation,
        "financial_inputs": {key: value for key, value in _mapping(financial).items() if key in _FINANCIAL_KEYS},
        "entry_plan": entry_plan,
        "hold_or_cut": hold_or_cut,
        "source_build": _source_build(source_build),
        "signal_evidence": signal_evidence,
        "context": {key: value for key, value in _mapping(context).items() if key in _CONTEXT_KEYS},
    })
    history_metadata = {}
    for index, (label, frame) in enumerate(histories.items(), 1):
        _check_identity(frame, ticker)
        # Only market series columns, never arbitrary holdings/account columns.
        allowed = {
            "open", "high", "low", "close", "adj close", "volume", "date", "datetime",
            "timestamp", "ma5", "ma20", "ma50", "ma120", "rsi", "mfi", "atr",
            "livequoteonly",
        }
        positions = []
        for i, col in enumerate(frame.columns):
            parts = col if isinstance(col, tuple) else (col,)
            if any(str(part).lower() in allowed for part in parts):
                if isinstance(col, tuple):
                    for part in parts:
                        if _text(part) and str(part).lower() not in allowed and _ticker(part) != ticker:
                            raise ValueError("Review OHLCV ticker mismatch")
                positions.append(i)
        clean = _json_value(frame.iloc[:, positions])
        columns = [json.dumps(col, ensure_ascii=False) if isinstance(col, list) else str(col) for col in clean["columns"]]
        csv_frame = pd.DataFrame(clean["rows"], columns=columns)
        csv_frame.insert(0, "_row_index", clean["index"])
        filename = f"ohlcv_{index:02d}.csv"
        frames[filename] = _csv_safe(csv_frame)
        history_metadata[_public_text(label)] = {
            "file": filename, "rows": len(frame), "columns": clean["columns"],
            "first_index": clean["index"][0] if len(frame) else None,
            "last_index": clean["index"][-1] if len(frame) else None,
            "attrs": _json_value({key: value for key, value in frame.attrs.items() if key in {
                "ticker", "source", "asof", "live_quote", "price_basis", "fetched_at",
            }}),
        }

    flags = _conflict_flags(sections)
    missing_sections = [name for name, value in sections.items() if value is None or value == {}]
    complete = not (_REQUIRED_SECTIONS.intersection(missing_sections)) and any(
        not frame.empty for frame in histories.values()
    )
    for name, section in sections.items():
        frames[f"{name}.csv"] = _csv_safe(pd.DataFrame(_flatten(section), columns=["field", "value"]))
    frames["conflict_flags.csv"] = _csv_safe(pd.DataFrame(
        flags, columns=["code", "left", "right", "note", "scope"],
    ))
    manifest = {
        "format": "stock-lab-precision-review", "version": EXPORT_VERSION,
        "captured_at": captured.isoformat(), "selected_ticker": ticker,
        "asof": _review_asof(histories),
        "completion": "complete" if complete and completion != "partial" else "partial",
        "stage": _public_text(_text(stage)),
        "result_ticker": _ticker(result_ticker), "source": _public_text(_text(source)),
        "scope": REVIEW_NOTICE, "recalculated_for_export": False,
        "fetched_for_export": False, "ohlcv": history_metadata,
        "source_build": sections["source_build"],
        "missing_sections": missing_sections,
        "conflict_flag_count": len(flags),
        "limitations": [
            "Captured at render time, not download time; market data may be older.",
            "Flags compare displayed wording only, not trading correctness; absence of flags is not agreement.",
            "CSV formula-like strings are apostrophe-prefixed. JSON preserves original safe text and nulls.",
            "Only explicitly supplied sections are included. No session state or account identities.",
        ],
    }
    snapshot = {"manifest": manifest, "sections": sections, "conflict_flags": flags}
    buffer = io.BytesIO(build_review_export_zip(frames))
    with zipfile.ZipFile(buffer, "a", zipfile.ZIP_DEFLATED) as archive:
        manifest["files"] = archive.namelist() + ["snapshot.json", "manifest.json"]
        archive.writestr("snapshot.json", json.dumps(snapshot, ensure_ascii=False, allow_nan=False, indent=2))
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, allow_nan=False, indent=2))
    return buffer.getvalue()


def _download_manifest(data):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return json.loads(archive.read("manifest.json"))


def _render_download(st, data, manifest, *, key_suffix="", saved=False):
    ticker = manifest["selected_ticker"]
    safe_ticker = re.sub(r"[^A-Z0-9._-]", "_", ticker)
    status = "완료 결과" if manifest["completion"] == "complete" else "부분 결과"
    st.caption(
        f"{ticker} · 기준일 {manifest['asof'] or '미확인'} · {status} · "
        f"저장 시각 {manifest['captured_at']}" + (" · 이전 저장 결과" if saved else "")
    )
    st.download_button(
        f"{ticker} 검토 ZIP 다운로드 ({status})", data=data, mime="application/zip",
        file_name=f"precision_review_{safe_ticker}.zip",
        key=f"precision_review_export_{manifest['source']}_{safe_ticker}{key_suffix}",
        on_click="ignore",
        help="현재 표시 결과를 검토용으로 내보냅니다. 매매 판단은 변경하지 않습니다.",
    )


def render_precision_review_download(st, **snapshot):
    """Render a download from local values; clicking must not rerun the app."""
    try:
        data = build_precision_review_export_zip(**snapshot)
    except (ValueError, TypeError, OverflowError):
        st.warning("검토 ZIP을 만들 수 없습니다. 선택 종목과 현재 표시 결과를 확인해 주세요.")
        return
    _render_download(st, data, _download_manifest(data))


class PrecisionReviewDownload:
    """Keep one session-local download ready before slower precision panels run."""

    def __init__(self, st, *, selected_ticker, owner, context=None):
        self.st = st
        self.ticker = _ticker(selected_ticker)
        self.owner = _text(owner).casefold()
        self.slot = st.empty()
        self.sequence = 0
        self.snapshot = {
            "selected_ticker": self.ticker, "result_ticker": self.ticker,
            "source": "precision", "context": context,
        }
        cached = st.session_state.pop(_READY_KEY, None)
        if self.owner and isinstance(cached, dict) and cached.get("owner") == self.owner:
            try:
                data = cached["data"]
                manifest = _download_manifest(data)
                if (
                    manifest["selected_ticker"] == manifest["result_ticker"] == self.ticker
                    and manifest["source"] == "precision"
                    and manifest["version"] == EXPORT_VERSION
                ):
                    with self.slot.container():
                        _render_download(st, data, manifest, key_suffix="_saved", saved=True)
                    st.session_state[_READY_KEY] = cached
                    return
            except (KeyError, ValueError, TypeError, zipfile.BadZipFile):
                pass
        self.update(completion="partial", stage="selection")

    def update(self, **snapshot):
        candidate = {**self.snapshot, **snapshot}
        candidate["captured_at"] = snapshot.get("captured_at") or datetime.now(timezone.utc)
        try:
            if _ticker(candidate["selected_ticker"]) != self.ticker:
                raise ValueError("Review snapshot ticker mismatch")
            data = build_precision_review_export_zip(**candidate)
        except (ValueError, TypeError, OverflowError):
            # A failed checkpoint must never leave another result downloadable.
            self.st.session_state.pop(_READY_KEY, None)
            with self.slot.container():
                self.st.warning("검토 ZIP을 만들 수 없습니다. 선택 종목과 현재 표시 결과를 확인해 주세요.")
            return
        self.snapshot = candidate
        self.sequence += 1
        with self.slot.container():
            _render_download(self.st, data, _download_manifest(data), key_suffix=f"_{self.sequence}")
        if self.owner:
            self.st.session_state[_READY_KEY] = {"owner": self.owner, "data": data}
