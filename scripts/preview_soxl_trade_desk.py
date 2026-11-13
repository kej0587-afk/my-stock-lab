"""Local-only visual QA with public frozen prices or explicitly synthetic data."""

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
import pandas as pd
import streamlit as st
from stock_lab_core.report_eventstudy import _exchange_schedule
from stock_lab_core.soxl_short_observation import build_short_observation
from stock_lab_core.soxl_trade_view import render_trade_desk, render_stats
from stock_lab_core.soxl_short_view import _time

st.set_page_config(page_title="SOXL 단기 계획 검증", layout="wide")
st.title("SOXL 단기 계획 검증")
st.caption("로컬 검증 화면 · 실제 주문/계좌 설정 없음")
mode = st.radio("검증 자료", ["저장된 실제 가격", "합성 지지 조건"], horizontal=True)
folder = ROOT / "cache/soxl_hour_research"
meta = json.loads((folder / "fetch.json").read_text(encoding="utf-8"))
now = pd.Timestamp(meta["captured_at"])
frames = {t:pd.read_parquet(folder/(t.replace("^","")+".parquet")) for t in ("SOXX","SOXL","^SOX","SMH","QQQ")}
schedule = _exchange_schedule("US", "2026-08-01", now.date().isoformat())
hourly = build_short_observation(frames,schedule,now)
if mode == "합성 지지 조건":
    st.warning("합성 테스트 · 실거래 값 아님")
    frame = hourly["frame"].copy()
    for col,value in (("Open",100.),("High",105.),("Low",94.),("Close",101.)):
        frame[col] = value
    hourly.update(frame=frame, channel=dict(lower=[95.],upper=[120.]),
                  plan=dict(stop=95.),status="합성 채널 내부")
    etf=frame.copy()
    for col,value in (("Open",60.),("High",62.),("Low",58.),("Close",60.)):
        etf[col]=value
    frames["SOXL"]=etf
payload={"frames":frames, "five_minute":{}}
decision={"execution_workflow":{"게이트상태":"방어우선","게이트근거":"기존 시장방어 유지(검증용)"}}
render_trade_desk(st,payload,hourly,schedule,now,decision,_time)
summary_path = ROOT / "cache/soxl_linked_research/summary.json"
if summary_path.exists():
    report = json.loads(summary_path.read_text(encoding="utf-8"))
    for policy in report["policies"]:
        report["policies"][policy]["trades"] = pd.read_csv(summary_path.parent/(policy+".csv")).to_dict("records")
    st.subheader("동일 고정 자료 재현 결과")
    render_stats(st,report,_time)
