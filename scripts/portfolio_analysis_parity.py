"""Parity check for app.build_portfolio_analysis_report on fixed synthetic holdings (no network).

Run in two trees with STOCK_LAB_FORCE_AUTH_MODE=public_demo:
    python -X utf8 scripts/portfolio_analysis_parity.py OUT_DIR
then `diff -r` the two OUT_DIRs. Prices are stubbed; benchmark calls read the same stubs.
"""
import hashlib, sys, json, math
import numpy as np, pandas as pd
sys.path.insert(0, ".")
import os
os.environ.setdefault("STOCK_LAB_FORCE_AUTH_MODE", "public_demo")
import app  # noqa: E402

def canon(x):
    if isinstance(x, pd.DataFrame):
        return {"df": json.loads(x.to_json(orient="split", double_precision=12, date_format="iso", default_handler=str))}
    if isinstance(x, pd.Series):
        return {"s": json.loads(x.to_json(orient="split", double_precision=12, date_format="iso", default_handler=str))}
    if isinstance(x, dict):
        return {str(k): canon(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [canon(v) for v in x]
    if isinstance(x, float):
        return "nan" if math.isnan(x) else round(x, 10)
    if isinstance(x, (np.floating,)):
        return canon(float(x))
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, pd.Timestamp):
        return x.isoformat()
    return x if isinstance(x, (int, str, bool, type(None))) else repr(x)

dates = pd.bdate_range("2025-11-03", periods=260)
rng = np.random.default_rng(7)
def walk(seed, drift=0.0005, vol=0.02, n=260):
    r = np.random.default_rng(seed).normal(drift, vol, n)
    return pd.Series(100 * np.cumprod(1 + r), index=dates[-n:])
hist = {"AAA": walk(1), "BBB": walk(2, vol=.035), "SOXL": walk(3, vol=.06), "069500.KS": walk(4), "VOO": walk(5),
        "SHORT": walk(6, n=15), "QLD": walk(8, vol=.04), "005930.KS": walk(9)}
def load(ticker, period="1y"):
    if ticker == "BOOM":
        raise RuntimeError("network")
    if ticker not in hist:
        return pd.DataFrame()
    return pd.DataFrame({"Close": hist[ticker]})
app.load_price_df = load

def holdings(rows):
    return pd.DataFrame(rows)
full = holdings([
    dict(티커="AAA", 자산명="에이", 원화환산=4_000_000., 목표비중=30., bucket="core", 운용대상=True, 기술적타점="DCA 진입 가능", 후보등급="A", 추세="상승", RS="강", RSI=55, MFI=60, MACD="+", SQZ="off", 평가손익=120_000., 수익률=3.1, 매입가=95., 보유량=10.),
    dict(티커="BBB", 자산명="비", 원화환산=2_500_000., 목표비중=20., bucket="swing", 운용대상=True, 기술적타점="과열 대기"),
    dict(티커="SOXL", 자산명="속슬", 원화환산=1_500_000., 목표비중=5., bucket="leverage", 운용대상=True, 기술적타점="하드차단 · 비중 초과"),
    dict(티커="QLD", 자산명="큐엘디", 원화환산=800_000., 목표비중=10., bucket="leverage", 운용대상=True, 기술적타점="매수 DCA"),
    dict(티커="005930.KS", 자산명="삼성전자", 원화환산=3_000_000., 목표비중=25., bucket="core", 운용대상=True, 기술적타점="과열 주의"),
    dict(티커="SHORT", 자산명="신규", 원화환산=300_000., 목표비중=2., bucket="core", 운용대상=True),
    dict(티커="BOOM", 자산명="오류", 원화환산=200_000., 목표비중=1., bucket="core", 운용대상=True),
    dict(티커="NODATA", 자산명="없음", 원화환산=100_000., 목표비중=1., bucket="core", 운용대상=True),
    dict(티커="SGOV", 자산명="대기", 원화환산=900_000., 목표비중=0., bucket="reserve", 운용대상=False),
])
cases = {
    "full": (full, 1_000_000., 500., 1380., 15.),
    "full_start": (full, 1_000_000., 500., 1380., 15.),
    "one": (full.iloc[:1].copy(), 0., 0., 1400., 10.),
    "empty": (holdings([]), 500_000., 100., 1350., 20.),
    "none": (None, 0., 0., 1300., 10.),
}
for name, (h, krw, usd, fx, reserve) in cases.items():
    kw = dict(analysis_start_date="2026-03-02") if name == "full_start" else {}
    try:
        out = app.build_portfolio_analysis_report(h.copy() if h is not None else None, krw, usd, fx, reserve, **kw)
        blob = json.dumps(canon(out), ensure_ascii=False, sort_keys=True, default=str)
    except Exception as exc:
        blob = "EXC " + type(exc).__name__ + ": " + str(exc)
    open(f"{sys.argv[1]}/{name}.json", "w").write(blob)
    print(name, hashlib.sha256(blob.encode()).hexdigest()[:16], len(blob))
