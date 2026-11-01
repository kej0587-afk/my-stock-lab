"""Portable drafts preserve IDs and reject corrupt files before any replacement."""

import json

import pandas as pd
import pytest

from stock_lab_core.account_performance_io import decode_ledger, empty_ledger, encode_ledger, ledger_accounts, MAX_BYTES
from stock_lab_core.account_performance import calculate_account_performance


def ledger():
    return {"valuations": pd.DataFrame({"date": pd.to_datetime(["2026-05-31", "2026-06-30"]),
                                        "account": ["ISA", "ISA"], "value_krw": [100000., 160000.]}),
            "flows": pd.DataFrame({"id": ["0001"], "date": pd.to_datetime(["2026-06-30"]), "account": ["ISA"],
                                   "amount": [50000.], "currency": ["KRW"], "fx_rate": [None]})}


def test_roundtrip_preserves_inputs_and_never_infers_completeness():
    source = ledger()
    original = {key: value.copy(deep=True) for key, value in source.items()}
    restored = decode_ledger(encode_ledger(source))
    assert restored["flows"].iloc[0]["id"] == "0001"
    assert ledger_accounts(restored) == ["ISA"]
    for key in source:
        pd.testing.assert_frame_equal(source[key], original[key])
    assert calculate_account_performance(**restored, account="ISA")["status"] == "missing"
    assert calculate_account_performance(**restored, account="ISA", flows_complete=True)["summary"]["return_pct"] == pytest.approx(10.)


def test_empty_and_incomplete_drafts_can_be_exported_without_fabricating_values():
    restored = decode_ledger(encode_ledger(empty_ledger()))
    assert all(frame.empty for frame in restored.values())
    source = ledger()
    source["valuations"].loc[0, "value_krw"] = float("nan")
    restored = decode_ledger(encode_ledger(source))
    assert pd.isna(restored["valuations"].loc[0, "value_krw"])
    assert calculate_account_performance(**restored, account="ISA", flows_complete=True)["status"] != "ready"


@pytest.mark.parametrize("change", [
    lambda p: p.update(version=True), lambda p: p.update(version=2),
    lambda p: p.update(currency_basis="USD"), lambda p: p.update(flow_timing="begin_of_day"),
    lambda p: p.update(valuations={}),
    lambda p: p["valuations"][0].update(date="2026/05/31"),
    lambda p: p["valuations"][0].update(date="2026-05-31T00:00:00Z"),
    lambda p: p["valuations"][0].update(date="9999-12-31"),
    lambda p: p["valuations"][0].update(value_krw=True),
    lambda p: p["valuations"][0].update(value_krw="100"),
    lambda p: p["valuations"][0].update(value_krw=10**1000),
    lambda p: p["flows"][0].update(id=123),
    lambda p: p["flows"][0].update(amount={"value": 100}),
    lambda p: p["flows"][0].update(unknown=1),
])
def test_bad_schema_or_cell_is_rejected_without_modifying_payload(change):
    payload = json.loads(encode_ledger(ledger()))
    change(payload)
    with pytest.raises(ValueError):
        decode_ledger(json.dumps(payload).encode())


@pytest.mark.parametrize("raw", [b'[]', b'{', b'\xff', b'{"version":1,"version":1}',
                                  b'{"x":NaN}', b'0' * (MAX_BYTES + 1)],
                         ids=["array", "broken_json", "encoding", "duplicate_key", "nan", "oversized"])
def test_invalid_files_fail_closed(raw):
    with pytest.raises(ValueError):
        decode_ledger(raw)


def test_json_overflow_exponent_and_infinite_export_fail_closed():
    raw = encode_ledger(ledger()).replace(b'100000.0', b'1e400')
    with pytest.raises(ValueError):
        decode_ledger(raw)
    source = ledger()
    source["valuations"].loc[0, "value_krw"] = float("inf")
    with pytest.raises(ValueError):
        encode_ledger(source)


def test_duplicated_events_remain_visible_for_engine_rejection_not_silently_deduplicated():
    source = ledger()
    source["flows"] = pd.concat([source["flows"], source["flows"]], ignore_index=True)
    restored = decode_ledger(encode_ledger(source))
    assert len(restored["flows"]) == 2
    assert calculate_account_performance(**restored, account="ISA", flows_complete=True)["status"] == "invalid"
