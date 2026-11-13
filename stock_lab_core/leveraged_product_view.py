"""Product/proxy presentation only; never feeds scores, returns or orders."""

import math
from types import MappingProxyType

from stock_lab_core import report_build

report_build.register_loaded_source(__name__, __file__)
IMPORTED_SOURCE = MappingProxyType(dict(report_build._LOADED[__name__]))


PRODUCTS = {
    "SOXL": (
        "NYSE Semiconductor Index의 일일 수익률 3배 목표",
        "SOXX는 같은 지수의 1배 비교 ETF입니다. SOX(PHLX)는 별도 지수이고, SMH는 다른 구성의 반도체 비교 ETF입니다.",
        "일일 재설정·복리·비용 때문에 여러 날 SOXX 수익률의 3배와 같지 않습니다.",
        "https://www.direxion.com/product/daily-semiconductor-bull-bear-3x-etfs",
    ),
    "RAM": (
        "DRAM ETF의 일일 수익률 2배 목표",
        "DRAM이 직접 비교 대상입니다. SOXX와 메모리 대표주는 보조 비교이며 RAM의 현재 편입비중이 아닙니다.",
        "DRAM의 국가·통화·메모리 집중 위험에 일일 2배 재설정과 파생상품 위험이 추가됩니다.",
        "https://roundhillinvestments.com/etf/ram/",
    ),
    "BITX": (
        "비트코인 일일 2배 목표 · 선물 중심 운용",
        "BTC-USD는 24시간 현물 비교, IBIT는 현물 ETF 비교입니다. IBIT를 2배 추종하거나 비트코인 현물을 직접 2배 보유하는 상품이 아닙니다.",
        "선물 롤·베이시스·비용과 일일 재설정 위험이 있습니다. 주말에도 BTC는 움직이지만 BITX 거래는 중단될 수 있어 재개장 갭이 생깁니다.",
        "https://www.volatilityshares.com/bitx",
    ),
    "418660": (
        "나스닥100 일일 2배 목표 · 국내상장 합성 ETF",
        "QQQ/QQQM은 나스닥100 비교 ETF입니다. ^IXIC는 나스닥종합, UUP는 달러 지수로 원/달러 환율 그 자체가 아닙니다.",
        "합성 거래상대방·환율·괴리율·일일 재설정 위험을 구분합니다. 한국 장중과 미국 전일 종가를 같은 시각 수익률로 비교할 수 없습니다.",
        "https://www.tigeretf.com/upload/etf/20240509105207003200.pdf",
    ),
}

ROLE_OVERRIDES = {
    ("SOXL", "SOXX"): "동일 지수 비교 ETF",
    ("SOXL", "SMH"): "다른 반도체 비교 ETF",
    ("RAM", "DRAM"): "추종 대상 ETF",
    ("BITX", "BTC-USD"): "24시간 현물 비교",
    ("BITX", "IBIT"): "현물 비교 ETF",
    ("418660", "QQQ"): "기초지수 비교 ETF",
    ("418660", "QQQM"): "기초지수 비교 ETF",
}


def product_key(ticker):
    return str(ticker or "").strip().upper().removesuffix(".KS")


def channel_basis_note(ticker):
    if product_key(ticker) not in PRODUCTS:
        return ""
    return (
        f"채널 기준: {ticker} 자체 가격·선택 시간봉의 자동 피벗 작도입니다. "
        "기초지수 채널을 배수 환산한 선이나 1시간·4시간 단타 검증 결과가 아닙니다. "
        "기초자산 목표 수익률에 2배·3배를 곱해 이 ETF의 목표가·손절가로 사용할 수 없습니다."
    )


def watch_display_rows(ticker, rows):
    """Copy, relabel and disclose the existing basket; keep raw values untouched."""
    result = []
    for row in rows:
        try:
            valid = math.isfinite(float(row.get("_1w")))
        except (TypeError, ValueError, OverflowError):
            valid = False
        # These roles match the existing recovery rule, not official index weights.
        included = row.get("구분") in {"기초 ETF", "섹터 확인", "시장 환경"} and valid
        display = {k: v for k, v in row.items() if not str(k).startswith("_")}
        aligned = bool(row.get("_comparison_version"))
        if aligned:
            display["기준 종가"] = display.pop("현재가", "-")
        labels = (("1D", "1거래일"), ("1W", "5거래일"), ("1M", "21거래일")) if aligned else (
            ("1D", "1봉 기준*"), ("1W", "5봉 기준*"), ("1M", "21봉 기준*"))
        for old, new in labels:
            if old in display:
                display[new] = display.pop(old)
        display["구분"] = ROLE_OVERRIDES.get((product_key(ticker), row.get("Ticker")), row.get("구분", ""))
        display["회복 평균 반영"] = "포함" if included else "미포함"
        result.append(display)
    return result


def render_product_basis(st, ticker):
    product = PRODUCTS.get(product_key(ticker))
    if not product:
        return False
    target, comparison, risk, source = product
    st.markdown("##### 상품 기준과 비교 대상")
    st.table([
        {"구분": "일일 목표", "내용": target},
        {"구분": "비교 대상", "내용": comparison},
        {"구분": "추가 위험", "내용": risk},
    ])
    st.caption(f"[운용사 상품 자료]({source}) · 투자 판단이나 수익 보장이 아닙니다.")
    return True


def render_watch_basis(st, ticker, rows):
    with st.expander("기초축/대표 프록시 확인", expanded=True):
        st.caption(
            "기존 '기초축 1W'는 아래 '회복 평균 반영: 포함' 행의 단순 평균이며 실제 기초지수 수익률이 아닙니다. "
            "대표주와 구성비가 아니라 비교용 목록입니다. BTC 현물 자체는 현재 회복 평균에 포함되지 않습니다."
            if product_key(ticker) == "BITX" else
            "기존 '기초축 1W'는 아래 '회복 평균 반영: 포함' 행의 단순 평균이며 실제 기초지수 수익률이 아닙니다. "
            "공식 편입비중이 아닌 비교용 목록입니다."
        )
        if rows:
            aligned = any(row.get("_comparison_version") for row in rows)
            if aligned:
                render_session_comparison(st, ticker, rows)
            else:
                st.dataframe(watch_display_rows(ticker, rows), width="stretch", hide_index=True)
        else:
            st.info("기초축 확인 데이터가 아직 없습니다.")
        if rows and any(row.get("_comparison_version") for row in rows):
            st.caption("최신 장중·프리·애프터·데이마켓 가격은 상단 현재가에서 별도로 확인합니다. "
                       "위 수익률에는 혼합하지 않습니다. 종가 확인 유예 15분 · 결측 시작/종료 가격은 대체하지 않습니다. "
                       "수익률 배수만으로 레버리지 ETF 목표가를 계산하지 않습니다.")
            return
        st.caption(
            "* 이력의 1·5·21봉 전 종가 대비 최근 조회가(없으면 마지막 종가) 기준입니다. "
            "이력이 짧으면 가용 첫 종가를 사용합니다. 시세·이력의 동일 세션은 미검증이며 정규장 확정 수익률이 아닙니다. "
            "BTC 일봉에는 주말이 포함되므로 5·21봉을 1주·1개월로 읽지 마세요."
        )


def render_session_comparison(st, ticker, rows):
    """Separate exchange clocks; keep wide audit metadata out of the main table."""
    for market, title in (("US", "미국 완료 정규장 비교"), ("KR", "한국 완료 정규장 · 미국과 별도 시각"),
                          ("CRYPTO", "24시간 현물 · 동시각 비교 미연결")):
        selected = [row for row in rows if row.get("_comparison_market") == market]
        if not selected:
            continue
        st.markdown("**" + title + "**")
        end = selected[0].get("종료 시각", "미연결")
        st.caption("비교 종료: " + end)
        columns = ("확인축", "Ticker", "기준 종가", "1거래일", "5거래일", "21거래일", "판정", "회복 평균 반영")
        table = [{key: row.get(key, "-") for key in columns} for row in watch_display_rows(ticker, selected)]
        st.dataframe(table, width="stretch", hide_index=True)
        missing = [row for row in selected if row.get("자료 상태") != "동일 시장 완료 세션 연결"]
        for row in missing:
            st.caption(f"{row['Ticker']}: {row['자료 상태']}")
    with st.expander("비교 시작·종료 시각과 자료 상태", expanded=False):
        audit = []
        for row in rows:
            for period, window in row.get("_comparison_windows", {}).items():
                audit.append({"Ticker": row["Ticker"], "기간": period,
                              "시작": window["start"], "종료": window["end"], "자료 상태": row["자료 상태"]})
        if audit:
            st.dataframe(audit, width="stretch", hide_index=True)
