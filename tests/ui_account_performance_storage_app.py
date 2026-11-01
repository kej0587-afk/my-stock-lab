"""Synthetic storage UI fixture; no credentials or real database connections."""

from hashlib import sha256
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import streamlit as st

from stock_lab_core.account_performance_io import decode_ledger, empty_ledger
from stock_lab_core.account_performance_view import render_account_performance
from tests.test_account_performance_storage_view import MemoryStore

st.set_page_config(page_title="Ledger storage validation", layout="wide")
st.title("개인 원장 저장 검증")
st.caption("합성 검증자료 · 접속 중 메모리 DB · 실제 Supabase 저장이나 실제 계좌가 아닙니다.")
owner = "A"
prefix = "account_performance_v1_" + sha256(owner.lower().encode()).hexdigest()[:20]
if "test_db" not in st.session_state:
    st.session_state["test_db"] = {}
    st.session_state["test_calls"] = []
    st.session_state["test_faults"] = {}
    st.session_state[prefix + "_draft"] = decode_ledger((ROOT / "docs/examples/account_performance_example.json").read_bytes())
    st.session_state[prefix + "_revision"] = 0
if st.button("검증용 접속 초안 초기화"):
    for key in list(st.session_state):
        if key.startswith(prefix):
            del st.session_state[key]
    st.session_state[prefix + "_draft"] = empty_ledger()
    st.session_state[prefix + "_revision"] = 0
    st.rerun()
render_account_performance(st, owner_scope=owner,
    store=MemoryStore(st.session_state["test_db"], st.session_state["test_calls"], st.session_state["test_faults"], owner))
