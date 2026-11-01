"""Portable performance drafts, separate from legacy monthly/account records."""

from datetime import date, datetime
import json
import math
import numbers

import pandas as pd

from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)


VALUATION_COLUMNS = ["date", "account", "value_krw"]
FLOW_COLUMNS = ["id", "date", "account", "amount", "currency", "fx_rate"]
MAX_BYTES = 1_000_000
MAX_ROWS = 5000


def empty_ledger():
    return {
        "valuations": pd.DataFrame({"date": pd.Series(dtype="datetime64[ns]"),
                                    "account": pd.Series(dtype=str), "value_krw": pd.Series(dtype=float)}),
        "flows": pd.DataFrame({"id": pd.Series(dtype=str), "date": pd.Series(dtype="datetime64[ns]"),
                               "account": pd.Series(dtype=str), "amount": pd.Series(dtype=float),
                               "currency": pd.Series(dtype=str), "fx_rate": pd.Series(dtype=float)}),
    }


def _cell(value):
    if value is None or value is pd.NaT or value is pd.NA:
        return None
    if isinstance(value, (date, datetime, pd.Timestamp)):
        if isinstance(value, (datetime, pd.Timestamp)) and (value.tzinfo is not None or value.time() != datetime.min.time()):
            raise ValueError("평가·입출금 날짜는 YYYY-MM-DD 일자만 허용합니다.")
        return value.strftime("%Y-%m-%d")
    if isinstance(value, numbers.Real) and not isinstance(value, bool):
        try:
            finite = math.isfinite(value)
        except OverflowError:
            raise ValueError("지원 범위 밖의 수치가 있습니다.") from None
        if not finite:
            if math.isnan(value):
                return None
            raise ValueError("무한대 수치는 원장에 저장할 수 없습니다.")
        return value.item() if hasattr(value, "item") else value
    return value


def _records(frame, columns):
    if not isinstance(frame, pd.DataFrame) or not set(columns).issubset(frame.columns):
        raise ValueError("원장 열 구성이 맞지 않습니다.")
    if len(frame) > MAX_ROWS:
        raise ValueError("원장은 표별 5,000행까지 지원합니다.")
    return [{col: _cell(row[col]) for col in columns} for row in frame.to_dict("records")]


def encode_ledger(ledger):
    payload = {"version": 1, "currency_basis": "KRW", "flow_timing": "end_of_day",
               "valuations": _records(ledger["valuations"], VALUATION_COLUMNS),
               "flows": _records(ledger["flows"], FLOW_COLUMNS)}
    raw = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    if len(raw) > MAX_BYTES:
        raise ValueError("원장 파일은 1MB까지 지원합니다.")
    return raw


def _unique_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError("원장에 중복된 JSON 항목이 있습니다.")
        obj[key] = value
    return obj


def decode_ledger(raw):
    if not isinstance(raw, bytes) or len(raw) > MAX_BYTES:
        raise ValueError("원장 파일은 UTF-8 JSON, 1MB 이하이어야 합니다.")
    try:
        payload = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_unique_object,
                             parse_constant=lambda _: (_ for _ in ()).throw(ValueError("비정상 수치")))
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("올바른 UTF-8 JSON 원장이 아닙니다.") from exc
    if (not isinstance(payload, dict) or type(payload.get("version")) is not int or payload["version"] != 1
            or payload.get("currency_basis") != "KRW" or payload.get("flow_timing") != "end_of_day"):
        raise ValueError("지원하는 원장 버전·원화 기준·일말 입출금 기준이 아닙니다.")
    result = empty_ledger()
    for name, columns in (("valuations", VALUATION_COLUMNS), ("flows", FLOW_COLUMNS)):
        rows = payload.get(name)
        if not isinstance(rows, list) or len(rows) > MAX_ROWS:
            raise ValueError("원장 표 형식 또는 행 수가 맞지 않습니다.")
        if any(not isinstance(row, dict) or set(row) != set(columns) for row in rows):
            raise ValueError("원장 열 구성이 맞지 않습니다.")
        if not rows:
            continue
        for row in rows:
            if row["date"] is not None:
                try:
                    parsed = date.fromisoformat(row["date"])
                    if parsed.isoformat() != row["date"]:
                        raise ValueError
                except (TypeError, ValueError):
                    raise ValueError("날짜는 YYYY-MM-DD 형식이어야 합니다.") from None
            for col in set(columns) - {"date"}:
                if row[col] is not None and not isinstance(row[col], (str, int, float, bool)):
                    raise ValueError("원장 셀에는 단일 값만 허용합니다.")
                if col in {"id", "account", "currency"} and row[col] is not None and not isinstance(row[col], str):
                    raise ValueError("계좌·거래ID·통화는 문자열이어야 합니다.")
                if col in {"value_krw", "amount", "fx_rate"} and row[col] is not None and type(row[col]) not in {int, float}:
                    raise ValueError("평가액·입출금액·환율은 숫자이어야 합니다.")
                if col in {"value_krw", "amount", "fx_rate"} and row[col] is not None:
                    try:
                        if not math.isfinite(float(row[col])):
                            raise ValueError
                    except (ValueError, OverflowError):
                        raise ValueError("지원 범위 밖의 수치가 있습니다.") from None
        # String IDs/accounts remain strings, including leading zeros.
        frame = pd.DataFrame(rows, columns=columns)
        try:
            frame["date"] = pd.to_datetime(frame["date"], format="%Y-%m-%d")
        except (ValueError, OverflowError):
            raise ValueError("지원 범위 밖의 날짜가 있습니다.") from None
        for col in set(columns) & {"value_krw", "amount", "fx_rate"}:
            frame[col] = frame[col].map(lambda value: float(value) if value is not None else float("nan"))
        result[name] = frame
    return result


def ledger_accounts(ledger):
    frame = ledger["valuations"]
    return sorted({str(value).strip() for value in frame.get("account", [])
                   if isinstance(value, str) and value.strip()})
