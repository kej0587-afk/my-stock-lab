"""Offline performance UI fixture; never reads private holdings or app secrets."""

from hashlib import sha256
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import streamlit as st

from stock_lab_core.account_performance_io import decode_ledger
from stock_lab_core.account_performance_view import render_account_performance

st.set_page_config(page_title="Account performance validation", layout="wide")
st.title("계좌 성과 검증 예제")
st.caption("합성 검증자료 · 실제 보유계좌나 투자성과가 아닙니다.")
owner = "offline-validation"
prefix = "account_performance_v1_" + sha256(owner.encode()).hexdigest()[:20]
if prefix + "_draft" not in st.session_state:
    st.session_state[prefix + "_draft"] = decode_ledger((ROOT / "docs/examples/account_performance_example.json").read_bytes())
    st.session_state[prefix + "_revision"] = 0
render_account_performance(st, owner_scope=owner)
