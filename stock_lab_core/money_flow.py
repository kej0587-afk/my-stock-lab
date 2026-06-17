"""Money-flow universe and calculations for Stock Lab.

Refactoring changelog (2026-05):
  [리팩토링]
  - _compute_ticker_metrics() 추출: calculate_money_flow_df / calculate_image_theme_flow_df
    의 중복 메트릭 계산 로직을 단일 함수로 통합
  - _compute_flow_score() 추출: 점수 공식을 한 곳에서 관리
  - _extract_ohlc_from_yf() 추출: yfinance 멀티인덱스 파싱 로직 분리

  [방법론 개선]
  - 가속도(accel): ret_3m - ret_6m (겹치는 구간) → ret_3m - ret_prev_3m (비겹치는 구간)
    * get_return_by_days_offset() 신규 추가
  - 거래량 가중치: 5% → 15% (돈흐름 강도 반영 강화)
  - 가중치 합계: 105 → 100 으로 정리 (1m:12, 3m:33, 6m:25, accel:15, vol:15)
  - 오버히팅 패널티: price_level > 0.85 구간에 × 40 감산 (price_level 활용)
  - 상태 분류: "고변동" 추가 (급격한 방향 전환 구간 포착)
  - 테마 로테이션: 동일 오버히팅 패널티 추가

  [티커 정리]
  - 재추가: 0117V0.KS / 0022T0.KS — FinanceDataReader 폴백 추가 후 조회 가능 확인,
    yfinance 직접 호출은 실패하지만 fdr 폴백이 처리함 (제거 불필요)
  - 수정: 315930.KS(KODEX Top5PlusTR, 오인) → 266360.KS(KODEX K콘텐츠), 섹터명 "K콘텐츠"로 변경
  - 수정: RR.L (롤스로이스 런던) → RYCEY (뉴욕 ADR)

  [유니버스 추가]
  - 미국 섹터: LIT (리튬/EV), BOTZ (로봇/AI), FINX (핀테크)
  - 매크로: HYG (하이일드채권, 위험선호 선행지표)

  [선택적 기능]
  - Alpha Vantage 폴백: AV_API_KEY 환경변수 설정 시 yfinance 실패 티커에 한해 사용
    * 무료 티어 25 calls/day / KRX 티커는 AV 미지원으로 폴백 제외
"""

import json
import logging
import os
import urllib.parse
import urllib.request

import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf

try:
    import FinanceDataReader as fdr
    _FDR_AVAILABLE = True
except ImportError:
    _FDR_AVAILABLE = False

try:
    from pykrx import stock as krx_stock
    _PYKRX_AVAILABLE = True
except ImportError:
    _PYKRX_AVAILABLE = False

for _streamlit_logger in (
    "streamlit.runtime.scriptrunner_utils.script_run_context",
    "streamlit.runtime.scriptrunner.script_run_context",
):
    logging.getLogger(_streamlit_logger).setLevel(logging.ERROR)


# ---------------------------------------------------------------------------
# 설정
# ---------------------------------------------------------------------------

# Alpha Vantage 선택적 폴백 (미국 상장 티커 한정)
# .env 또는 시스템 환경변수에 AV_API_KEY=<key> 설정 시 활성화
_AV_API_KEY: str = os.getenv("AV_API_KEY", "")

# yfinance 지원 불안정 해외 거래소 접미사
# .T(도쿄)는 fdr(TSE:) 폴백으로 처리 / .TW .VI .L 은 폴백 없음
_UNRELIABLE_SUFFIXES = {"T", "TW", "VI", "L"}

_NAVER_ETF_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://stock.naver.com/",
}

_NAVER_KR_ETF_RANKINGS = [
    ("국내 거래대금", "tradingValueDesc", 3.0),
    ("국내 거래량급증", "tradingVolumeIncreaseRateDesc", 2.0),
    ("국내 1M수익률", "returnRate1mDesc", 1.5),
    ("국내 3M수익률", "returnRate3mDesc", 2.5),
    ("국내 6M수익률", "returnRate6mDesc", 1.5),
]

_NAVER_US_ETF_RANKINGS = [
    ("미국 거래대금", "priceTop", 3.0),
    ("미국 거래량", "quantTop", 2.0),
    ("미국 시총", "marketValue", 1.5),
]


# ---------------------------------------------------------------------------
# 유틸리티
# ---------------------------------------------------------------------------

def finite_num(x) -> bool:
    """NaN / Inf / None 아닌 유효 숫자인지 확인."""
    return x is not None and not pd.isna(x) and np.isfinite(float(x))


def _to_float(value, default=np.nan) -> float:
    try:
        if value is None or value == "":
            return default
        return float(str(value).replace(",", ""))
    except Exception:
        return default


def _rank_bonus(weight: float, rank: int, limit: int) -> float:
    if limit <= 0:
        return 0.0
    rank_factor = max(0.0, 1.0 - ((rank - 1) / max(limit, 1)))
    return float(weight) * rank_factor


def _open_naver_json(url: str, referer: str) -> object:
    headers = dict(_NAVER_ETF_HEADERS)
    headers["Referer"] = referer
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=8) as res:
        raw = res.read().decode("utf-8", errors="ignore")
    return json.loads(raw)


def _normalize_naver_us_etf_symbol(value: str) -> str:
    symbol = str(value or "").strip().upper()
    if "." in symbol:
        symbol = symbol.split(".", 1)[0]
    return symbol


def _merge_naver_rank_item(items: dict, ticker: str, name: str, rank_label: str, rank: int, bonus: float, market: str):
    if not ticker:
        return
    key = normalize_money_flow_ticker(ticker)
    display_name = str(name or "").strip() or key
    if key not in items:
        items[key] = {
            "구분": "네이버 ETF 랭킹",
            "섹터": display_name,
            "ticker": key,
            "name": display_name,
            "네이버랭킹": [],
            "랭킹보조점수": 0.0,
            "네이버시장": market,
        }
    else:
        if display_name and (not items[key].get("name") or items[key].get("name") == key):
            items[key]["name"] = display_name
        if display_name and items[key].get("섹터") in {key, rank_label, ""}:
            items[key]["섹터"] = display_name
    items[key]["네이버랭킹"].append(f"{rank_label} #{rank}")
    items[key]["랭킹보조점수"] += float(bonus)


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_naver_etf_ranking_universe(limit_per_rank: int = 8, max_total: int = 45) -> list[dict]:
    """네이버 국내/미국 ETF 랭킹 상위만 후보풀로 가져온다.

    전체 ETF를 매번 긁지 않고 거래대금·거래량·수익률 상위권만 가져와
    돈흐름 레이더의 후보 발견력을 보강한다. 실패해도 기존 유니버스는 그대로 동작한다.
    """
    limit = max(1, min(int(limit_per_rank or 8), 20))
    merged: dict[str, dict] = {}

    for rank_label, listing_type, weight in _NAVER_KR_ETF_RANKINGS:
        url = (
            "https://stock.naver.com/api/stockSecurity/etfs/v1/domestic?"
            + urllib.parse.urlencode({"listingType": listing_type, "size": limit, "index": 0})
        )
        try:
            payload = _open_naver_json(url, "https://stock.naver.com/market/stock/kr/etf/priceTop")
            rows = payload.get("items", []) if isinstance(payload, dict) else []
        except Exception:
            rows = []
        for idx, row in enumerate(rows[:limit], start=1):
            code = str(row.get("itemCode", "")).strip()
            if not code:
                continue
            _merge_naver_rank_item(
                merged,
                f"{code}.KS",
                str(row.get("itemName", "") or code),
                rank_label,
                idx,
                _rank_bonus(weight, idx, limit),
                "KR",
            )

    for rank_label, order_type, weight in _NAVER_US_ETF_RANKINGS:
        url = (
            "https://stock.naver.com/api/foreign/market/etf/usa?"
            + urllib.parse.urlencode({"orderType": order_type, "startIdx": 0, "pageSize": limit})
        )
        try:
            rows = _open_naver_json(url, "https://stock.naver.com/market/stock/usa/etf/priceTop")
            if not isinstance(rows, list):
                rows = []
        except Exception:
            rows = []
        for idx, row in enumerate(rows[:limit], start=1):
            symbol = _normalize_naver_us_etf_symbol(row.get("reutersCode", "") or row.get("symbolCode", ""))
            if not symbol:
                continue
            _merge_naver_rank_item(
                merged,
                symbol,
                str(row.get("koreanCodeName") or row.get("englishCodeName") or symbol),
                rank_label,
                idx,
                _rank_bonus(weight, idx, limit),
                "US",
            )

    out = []
    for item in merged.values():
        item["랭킹보조점수"] = min(float(item.get("랭킹보조점수", 0.0)), 6.0)
        item["네이버랭킹"] = ", ".join(dict.fromkeys(item.get("네이버랭킹", [])))
        out.append(item)

    out.sort(key=lambda r: float(r.get("랭킹보조점수", 0.0)), reverse=True)
    return out[:max_total]


def _map_naver_kr_theme_to_stocklab_theme(name: str) -> str:
    """네이버 국내 테마명을 Stock Lab 내부 테마명으로 느슨하게 매핑."""
    text = str(name or "").replace(" ", "").upper()
    if not text:
        return ""
    if any(k in text for k in ["MLCC", "적층세라믹", "콘덴서", "전장부품", "카메라모듈"]):
        return "전자부품·MLCC"
    if any(k in text for k in ["2차전지", "리튬", "니켈", "전고체", "나트륨이온", "배터리"]):
        return "2차전지 밸류체인"
    if any(k in text for k in ["로봇", "휴머노이드", "스마트팩토리", "자동화"]):
        return "휴머노이드·로봇"
    if any(k in text for k in ["PCB", "FPCB", "기판", "FC-BGA", "ABF"]):
        return "PCB·기판 글로벌"
    if any(k in text for k in ["반도체", "HBM", "CXL", "온디바이스", "소부장"]):
        return "국내 AI 반도체·소부장"
    if any(k in text for k in ["원자력", "원전", "SMR", "우라늄"]):
        return "글로벌 원전·SMR"
    if any(k in text for k in ["전력", "전선", "변압", "전력설비", "스마트그리드", "ESS"]):
        return "전력·에너지 인프라"
    if any(k in text for k in ["방산", "우주", "항공", "드론", "위성"]):
        return "우주항공·방산"
    if any(k in text for k in ["조선", "해양", "LNG", "선박"]):
        return "조선·해양"
    if any(k in text for k in ["바이오", "제약", "의료", "헬스", "신약"]):
        return "바이오·제약"
    if any(k in text for k in ["화장품", "뷰티", "패션", "소비재"]):
        return "K-뷰티·소비재"
    if any(k in text for k in ["광통신", "포토닉", "데이터센터", "광모듈"]):
        return "포토닉스·광통신"
    if any(k in text for k in ["생명보험", "손해보험", "보험", "토스", "핀테크", "은행", "증권"]):
        return "한국 금융"
    if any(k in text for k in ["통신", "5G", "LTE", "통신장비"]):
        return "전력·에너지 인프라"
    if any(k in text for k in ["백화점", "면세점", "홈쇼핑", "소매유통", "유통", "출산장려"]):
        return "K-뷰티·소비재"
    if any(k in text for k in ["게임", "웹툰", "저작권", "콘텐츠", "엔터"]):
        return "K-뷰티·소비재"
    if any(k in text for k in ["자동차", "전기차", "수소차", "자율주행"]):
        return "2차전지 밸류체인"
    if any(k in text for k in ["재개발", "도시개발", "SOC", "인프라", "건설", "터미널"]):
        return "글로벌 인프라·산업재"
    if any(k in text for k in ["비트코인", "BITCOIN", "가상화폐", "암호화폐"]):
        return "미국 금융·핀테크"
    return ""


def _map_naver_etf_to_stocklab_theme(name: str, ticker: str = "") -> str:
    """네이버 ETF 랭킹명을 내부 테마로 느슨하게 연결."""
    symbol = normalize_money_flow_ticker(ticker)
    if symbol in ETF_TO_THEME:
        return ETF_TO_THEME.get(symbol, "")
    text = (str(name or "") + " " + str(symbol or "")).replace(" ", "").upper()
    if not text:
        return ""
    if symbol in {"VEA", "IEFA", "VTI", "VUG", "VTV", "IWM", "BITO", "IBIT"}:
        return ""
    if any(k in text for k in ["반도체", "필라델피아", "SEMICONDUCTOR", "SOXX", "SMH", "SOXL", "SOXS", "하이닉스", "삼성전자"]):
        return "국내 AI 반도체·소부장" if symbol.endswith(".KS") else "미국 AI·빅테크"
    if any(k in text for k in ["NASDAQ", "나스닥", "QQQ", "TQQQ", "QLD", "빅테크", "TOP10"]):
        return "미국 AI·빅테크"
    if any(k in text for k in ["전력", "전기", "수소", "인프라", "전선", "NETWORK", "GRID"]):
        return "전력·에너지 인프라"
    if any(k in text for k in ["원전", "원자력", "우라늄", "SMR"]):
        return "글로벌 원전·SMR"
    if any(k in text for k in ["2차전지", "전고체", "배터리", "BATTERY", "LITHIUM", "LIT", "전기차", "EV"]):
        return "2차전지 밸류체인"
    if any(k in text for k in ["방산", "우주", "항공", "SPACE", "DEFENSE", "AEROSPACE"]):
        return "우주항공·방산"
    if any(k in text for k in ["조선", "해양", "선박", "LNG"]):
        return "조선·해양"
    if any(k in text for k in ["바이오", "헬스", "제약", "HEALTH", "BIOTECH"]):
        return "바이오·제약" if symbol.endswith(".KS") else "미국 헬스케어·바이오텍"
    if any(k in text for k in ["화장품", "뷰티", "소비재", "K뷰티"]):
        return "K-뷰티·소비재"
    if any(k in text for k in ["금융", "은행", "증권", "보험", "FINANCIAL", "FINTECH"]):
        return "한국 금융" if symbol.endswith(".KS") else "미국 금융·핀테크"
    if any(k in text for k in ["로봇", "ROBOT", "BOTZ", "AI"]):
        return "휴머노이드·로봇"
    if any(k in text for k in ["구리", "COPPER", "산업재", "소재", "VALUEUP", "밸류업"]):
        return "글로벌 인프라·산업재"
    if any(k in text for k in ["게임", "GAME", "저작권", "COPYRIGHT", "콘텐츠", "CONTENT"]):
        return "K-뷰티·소비재"
    if any(k in text for k in ["자동차", "부품", "전기&수소차", "수소차", "CAR", "AUTO"]):
        return "2차전지 밸류체인"
    if any(k in text for k in ["BITCOIN", "비트코인"]):
        return "미국 금융·핀테크"
    return ""


def _is_naver_etf_mapping_excluded(name: str, ticker: str = "") -> tuple[bool, str]:
    """광범위 지수/레버리지/인버스 등 테마 매핑 대상이 아닌 ETF를 커버리지 분모에서 제외."""
    text = (str(name or "") + " " + str(ticker or "")).replace(" ", "").upper()
    if any(k in text for k in ["레버리지", "인버스", "BEAR", "BULL", "2X", "3X", "ULTRA", "ULTRAPRO", "선물레버리지"]):
        return True, "레버리지/인버스 ETF"
    if any(k in text for k in ["단일종목", "삼성전자", "SK하이닉스", "엔비디아", "테슬라"]) and "ETF" in text:
        return True, "단일종목 ETF"
    if any(k in text for k in ["KODEX200", "TIGER200", "KOSPI200", "S&P500", "S&P 500", "SPY", "VOO", "KODEX코스피"]):
        return True, "광범위 시장지수 ETF"
    if any(k in text for k in ["TOTALSTOCK", "RUSSELL2000", "GROWTHINDEX", "VALUEINDEX", "EAFE", "선진국", "전세계", "글로벌주식"]):
        return True, "광범위 시장지수 ETF"
    if any(k in text for k in ["BITCOIN", "비트코인", "IBIT", "BITO"]):
        return True, "크립토 ETF(내부 테마 미운영)"
    return False, ""


def _add_naver_theme_evidence(bucket: dict, theme: str, label: str, score: float, rise_ratio=np.nan):
    if not theme:
        return
    entry = bucket.setdefault(theme, {
        "점수_네이버테마": 0.0,
        "네이버테마근거": [],
        "네이버테마상승비율": [],
    })
    entry["점수_네이버테마"] += float(score)
    if label:
        entry["네이버테마근거"].append(str(label))
    if finite_num(rise_ratio):
        entry["네이버테마상승비율"].append(float(rise_ratio))


@st.cache_data(ttl=900, show_spinner=False)
def fetch_naver_theme_context_snapshot(kr_limit: int = 80, us_limit: int = 12) -> dict[str, dict]:
    """네이버 테마/미국 업종 화면을 보조 신호로 요약한다.

    네이버 화면의 당일 테마 강도는 단기 노이즈가 크므로, 테마돈흐름점수에는
    작은 보조점수로만 반영하고 2주/1개월 가격 흐름이 최종 판정을 우선한다.
    """
    out: dict[str, dict] = {}

    try:
        url = (
            "https://stock.naver.com/api/domestic/market/theme/list?"
            + urllib.parse.urlencode({
                "startIdx": 0,
                "pageSize": max(10, min(int(kr_limit or 80), 120)),
                "sortType": "changeRate",
            })
        )
        rows = _open_naver_json(url, "https://stock.naver.com/market/stock/kr/theme/1")
        if not isinstance(rows, list):
            rows = []
    except Exception:
        rows = []

    for idx, row in enumerate(rows, start=1):
        theme = _map_naver_kr_theme_to_stocklab_theme(row.get("name", ""))
        if not theme:
            continue
        change = _to_float(row.get("changeRate"), 0.0) / 100.0
        recent3 = _to_float(row.get("recent3daysChangeRate"), 0.0) / 100.0
        total_cnt = max(1.0, _to_float(row.get("totalCnt"), 1.0))
        rise_ratio = _to_float(row.get("riseCnt"), 0.0) / total_cnt
        amount = max(0.0, _to_float(row.get("totalAccAmount"), 0.0))
        rank_bonus = _rank_bonus(2.5, idx, min(len(rows), 40))
        amount_bonus = min(np.log10(amount + 1.0) / 3.0, 3.0) if amount > 0 else 0.0
        raw_score = (change * 65.0) + (recent3 * 18.0) + ((rise_ratio - 0.5) * 5.0) + rank_bonus + amount_bonus
        score = max(-3.0, min(raw_score, 7.0))
        label = f"{row.get('name', '')} {change:+.1%}"
        _add_naver_theme_evidence(out, theme, label, score, rise_ratio)

    try:
        url = (
            "https://stock.naver.com/api/foreign/market/USA/upjong/57201020/list?"
            + urllib.parse.urlencode({"orderType": "priceTop", "startIdx": 0, "pageSize": max(5, min(int(us_limit or 12), 25))})
        )
        us_rows = _open_naver_json(url, "https://stock.naver.com/market/stock/usa/industry/57201020")
        if not isinstance(us_rows, list):
            us_rows = []
    except Exception:
        us_rows = []

    if us_rows:
        changes = []
        labels = []
        for row in us_rows[:us_limit]:
            symbol = _normalize_naver_us_etf_symbol(row.get("symbolCode") or row.get("reutersCode", ""))
            change = max(-0.08, min(_to_float(row.get("fluctuationsRatio"), 0.0) / 100.0, 0.08))
            changes.append(change)
            if symbol:
                labels.append(f"{symbol} {change:+.1%}")
        avg_change = float(np.nanmean(changes)) if changes else 0.0
        rise_ratio = float(np.mean([x > 0 for x in changes])) if changes else np.nan
        score = max(-2.5, min(avg_change * 30.0 + (rise_ratio - 0.5) * 3.0 + 1.0, 4.0))
        _add_naver_theme_evidence(
            out,
            "미국 AI·빅테크",
            "미국 소프트웨어 " + ", ".join(labels[:4]),
            score,
            rise_ratio,
        )

    normalized = {}
    for theme, entry in out.items():
        evidence = list(dict.fromkeys(entry.get("네이버테마근거", [])))[:4]
        ratios = entry.get("네이버테마상승비율", [])
        normalized[theme] = {
            "점수_네이버테마": max(-4.0, min(float(entry.get("점수_네이버테마", 0.0)), 8.0)),
            "네이버테마근거": ", ".join(evidence),
            "네이버테마상승비율": float(np.nanmean(ratios)) if ratios else np.nan,
        }
    return normalized


@st.cache_data(ttl=900, show_spinner=False)
def fetch_naver_theme_coverage_snapshot(kr_limit: int = 100, etf_limit: int = 10) -> dict[str, object]:
    """네이버 강세 테마/ETF가 내부 money_flow 테마로 얼마나 매핑되는지 점검한다.

    실시간 판정에는 기존 가격/거래량 기반 점수를 우선 사용하고, 이 함수는
    누락된 테마를 찾기 위한 운영 진단용 데이터만 만든다.
    """
    mapped: list[dict] = []
    unmapped: list[dict] = []
    excluded: list[dict] = []

    try:
        url = (
            "https://stock.naver.com/api/domestic/market/theme/list?"
            + urllib.parse.urlencode({
                "startIdx": 0,
                "pageSize": max(10, min(int(kr_limit or 100), 120)),
                "sortType": "changeRate",
            })
        )
        rows = _open_naver_json(url, "https://stock.naver.com/market/stock/kr/theme/1")
        if not isinstance(rows, list):
            rows = []
    except Exception:
        rows = []

    for idx, row in enumerate(rows, start=1):
        name = str(row.get("name", "") or "").strip()
        if not name:
            continue
        change = _to_float(row.get("changeRate"), 0.0) / 100.0
        recent3 = _to_float(row.get("recent3daysChangeRate"), 0.0) / 100.0
        total_cnt = max(1.0, _to_float(row.get("totalCnt"), 1.0))
        rise_ratio = _to_float(row.get("riseCnt"), 0.0) / total_cnt
        amount = max(0.0, _to_float(row.get("totalAccAmount"), 0.0))
        theme = _map_naver_kr_theme_to_stocklab_theme(name)
        item = {
            "출처": "네이버 국내테마",
            "네이버명": name,
            "내부테마": theme,
            "순위": idx,
            "등락률": change,
            "3일등락률": recent3,
            "상승비율": rise_ratio,
            "거래대금": amount,
            "상태": "매핑완료" if theme else "미분류",
        }
        (mapped if theme else unmapped).append(item)

    try:
        etf_rows = fetch_naver_etf_ranking_universe(limit_per_rank=etf_limit, max_total=60)
    except Exception:
        etf_rows = []

    for item in etf_rows:
        ticker = normalize_money_flow_ticker(item.get("ticker", ""))
        if not ticker:
            continue
        name = str(item.get("name") or item.get("섹터") or ticker)
        excluded_flag, excluded_reason = _is_naver_etf_mapping_excluded(name, ticker)
        theme = _map_naver_etf_to_stocklab_theme(name, ticker)
        row = {
            "출처": f"네이버 ETF랭킹/{item.get('네이버시장', '')}",
            "네이버명": name,
            "티커": ticker,
            "내부테마": theme,
            "순위": np.nan,
            "등락률": np.nan,
            "3일등락률": np.nan,
            "상승비율": np.nan,
            "거래대금": np.nan,
            "네이버랭킹": item.get("네이버랭킹", ""),
            "랭킹보조점수": item.get("랭킹보조점수", 0.0),
            "상태": "제외" if excluded_flag else ("매핑완료" if theme else "미분류"),
            "제외사유": excluded_reason,
        }
        if excluded_flag:
            excluded.append(row)
        else:
            (mapped if theme else unmapped).append(row)

    mapped = sorted(
        mapped,
        key=lambda r: (
            float(r.get("랭킹보조점수", 0.0) or 0.0),
            float(r.get("등락률", 0.0) or 0.0),
            -float(r.get("순위", 9999) if finite_num(r.get("순위", np.nan)) else 9999),
        ),
        reverse=True,
    )
    unmapped = sorted(
        unmapped,
        key=lambda r: (
            float(r.get("랭킹보조점수", 0.0) or 0.0),
            float(r.get("등락률", 0.0) or 0.0),
            -float(r.get("순위", 9999) if finite_num(r.get("순위", np.nan)) else 9999),
        ),
        reverse=True,
    )
    return {
        "mapped": mapped[:60],
        "unmapped": unmapped[:40],
        "excluded": excluded[:40],
        "summary": {
            "mapped_count": len(mapped),
            "unmapped_count": len(unmapped),
            "excluded_count": len(excluded),
            "coverage_pct": (len(mapped) / max(len(mapped) + len(unmapped), 1)) * 100,
        },
    }


def build_money_flow_universe_with_naver_rankings() -> list[dict]:
    base = [
        dict(item, ticker=normalize_money_flow_ticker(item["ticker"]), 랭킹보조점수=0.0, 네이버랭킹="")
        for item in MONEY_FLOW_UNIVERSE
    ]
    base_tickers = {item["ticker"] for item in base}

    try:
        naver_items = fetch_naver_etf_ranking_universe()
    except Exception:
        naver_items = []

    naver_by_ticker = {normalize_money_flow_ticker(item.get("ticker", "")): item for item in naver_items}
    for item in base:
        naver = naver_by_ticker.get(item["ticker"])
        if not naver:
            continue
        item["랭킹보조점수"] = float(naver.get("랭킹보조점수", 0.0))
        item["네이버랭킹"] = naver.get("네이버랭킹", "")
        item["네이버시장"] = naver.get("네이버시장", "")

    for item in naver_items:
        ticker = normalize_money_flow_ticker(item.get("ticker", ""))
        if ticker and ticker not in base_tickers:
            base.append(dict(item, ticker=ticker))
            base_tickers.add(ticker)

    return base


# ---------------------------------------------------------------------------
# 유니버스 정의
# ---------------------------------------------------------------------------

MONEY_FLOW_UNIVERSE = [
    # ── 미국 섹터 ──────────────────────────────────────────────────────────
    {"구분": "미국 섹터", "섹터": "나스닥",          "ticker": "QQQ",  "name": "Invesco QQQ Trust"},
    {"구분": "미국 섹터", "섹터": "S&P500",          "ticker": "VOO",  "name": "Vanguard S&P 500 ETF"},
    {"구분": "미국 섹터", "섹터": "다우존스",        "ticker": "DIA",  "name": "SPDR Dow Jones Industrial Average ETF"},
    {"구분": "미국 섹터", "섹터": "반도체 VanEck",   "ticker": "SMH",  "name": "VanEck Semiconductor ETF"},
    {"구분": "미국 섹터", "섹터": "반도체 iShares",  "ticker": "SOXX", "name": "iShares Semiconductor ETF"},
    {"구분": "미국 섹터", "섹터": "기술",            "ticker": "XLK",  "name": "Technology Select Sector SPDR"},
    {"구분": "미국 섹터", "섹터": "커뮤니케이션",    "ticker": "XLC",  "name": "Communication Services SPDR"},
    {"구분": "미국 섹터", "섹터": "금융",            "ticker": "XLF",  "name": "Financial Select Sector SPDR"},
    {"구분": "미국 섹터", "섹터": "헬스케어",        "ticker": "XLV",  "name": "Health Care Select Sector SPDR"},
    {"구분": "미국 섹터", "섹터": "에너지",          "ticker": "XLE",  "name": "Energy Select Sector SPDR"},
    {"구분": "미국 섹터", "섹터": "산업재",          "ticker": "XLI",  "name": "Industrial Select Sector SPDR"},
    {"구분": "미국 섹터", "섹터": "소재",            "ticker": "XLB",  "name": "Materials Select Sector SPDR"},
    {"구분": "미국 섹터", "섹터": "경기소비재",      "ticker": "XLY",  "name": "Consumer Discretionary SPDR"},
    {"구분": "미국 섹터", "섹터": "필수소비재",      "ticker": "XLP",  "name": "Consumer Staples SPDR"},
    {"구분": "미국 섹터", "섹터": "유틸리티",        "ticker": "XLU",  "name": "Utilities Select Sector SPDR"},
    {"구분": "미국 섹터", "섹터": "부동산",          "ticker": "VNQ",  "name": "Vanguard Real Estate ETF"},
    {"구분": "미국 섹터", "섹터": "바이오",          "ticker": "IBB",  "name": "iShares Biotechnology ETF"},
    {"구분": "미국 섹터", "섹터": "신재생",          "ticker": "ICLN", "name": "iShares Global Clean Energy ETF"},
    {"구분": "미국 섹터", "섹터": "인프라",          "ticker": "PAVE", "name": "Global X U.S. Infrastructure Development ETF"},
    {"구분": "미국 섹터", "섹터": "방산",            "ticker": "SHLD", "name": "Global X Defense Tech ETF"},
    {"구분": "미국 섹터", "섹터": "항공방산",        "ticker": "ITA",  "name": "iShares U.S. Aerospace & Defense ETF"},
    {"구분": "미국 섹터", "섹터": "소프트웨어",      "ticker": "IGV",  "name": "iShares Expanded Tech-Software Sector ETF"},
    {"구분": "미국 섹터", "섹터": "사이버보안",      "ticker": "CIBR", "name": "First Trust NASDAQ Cybersecurity ETF"},
    {"구분": "미국 섹터", "섹터": "주택건설",        "ticker": "XHB",  "name": "SPDR S&P Homebuilders ETF"},
    {"구분": "미국 섹터", "섹터": "원자재(구리)",    "ticker": "COPX", "name": "Global X Copper Miners ETF"},
    # [신규] 테마 섹터
    {"구분": "미국 섹터", "섹터": "리튬/EV밸류체인", "ticker": "LIT",  "name": "Global X Lithium & Battery Tech ETF"},
    {"구분": "미국 섹터", "섹터": "로봇/AI",         "ticker": "BOTZ", "name": "Global X Robotics & AI ETF"},
    {"구분": "미국 섹터", "섹터": "핀테크",          "ticker": "FINX", "name": "Global X FinTech ETF"},
    # [신규] 우주·양자·AI그리드
    {"구분": "미국 섹터", "섹터": "우주/위성통신",   "ticker": "UFO",  "name": "Procure Space ETF"},
    {"구분": "미국 섹터", "섹터": "양자컴퓨팅",      "ticker": "QTUM", "name": "Defiance Quantum ETF"},
    {"구분": "미국 섹터", "섹터": "AI전력그리드",    "ticker": "GRID", "name": "First Trust NASDAQ Clean Edge Smart Grid & Infrastructure ETF"},

    # ── 한국 섹터 ──────────────────────────────────────────────────────────
    {"구분": "한국 섹터", "섹터": "코스피",       "ticker": "069500.KS", "name": "KODEX 200"},
    {"구분": "한국 섹터", "섹터": "코스닥",       "ticker": "229200.KS", "name": "KODEX 코스닥150"},
    {"구분": "한국 섹터", "섹터": "반도체",       "ticker": "396500.KS", "name": "TIGER 반도체TOP10"},
    {"구분": "한국 섹터", "섹터": "IT/기술",      "ticker": "139260.KS", "name": "TIGER 200 IT"},
    {"구분": "한국 섹터", "섹터": "2차전지",      "ticker": "305540.KS", "name": "TIGER 2차전지테마"},
    {"구분": "한국 섹터", "섹터": "전력인프라",   "ticker": "487240.KS", "name": "KODEX AI전력핵심설비"},
    {"구분": "한국 섹터", "섹터": "전력기기",    "ticker": "0117V0.KS", "name": "TIGER 코리아AI전력기기TOP3플러스"},
    {"구분": "한국 섹터", "섹터": "원자력",       "ticker": "434730.KS", "name": "HANARO 원자력iSelect"},
    {"구분": "한국 섹터", "섹터": "원자력TOP10",  "ticker": "433500.KS", "name": "ACE 원자력TOP10"},
    {"구분": "한국 섹터", "섹터": "조선",         "ticker": "494670.KS", "name": "TIGER 조선TOP10"},
    {"구분": "한국 섹터", "섹터": "방산",         "ticker": "449450.KS", "name": "PLUS K방산"},
    {"구분": "한국 섹터", "섹터": "K-뷰티",       "ticker": "479850.KS", "name": "HANARO K-뷰티"},
    {"구분": "한국 섹터", "섹터": "화장품",       "ticker": "228790.KS", "name": "TIGER 화장품"},
    {"구분": "한국 섹터", "섹터": "K콘텐츠",      "ticker": "266360.KS", "name": "KODEX K콘텐츠"},   # 카카오/NAVER(웹툰) + 크래프톤/엔씨소프트(게임) + 하이브
    {"구분": "한국 섹터", "섹터": "에너지",       "ticker": "139250.KS", "name": "TIGER 200 에너지화학"},
    {"구분": "한국 섹터", "섹터": "금융",         "ticker": "139270.KS", "name": "TIGER 200 금융"},
    {"구분": "한국 섹터", "섹터": "바이오",       "ticker": "244580.KS", "name": "KODEX 바이오"},
    {"구분": "한국 섹터", "섹터": "부동산",       "ticker": "329200.KS", "name": "TIGER 리츠부동산인프라"},
    {"구분": "한국 섹터", "섹터": "건설/유틸",    "ticker": "139220.KS", "name": "TIGER 200 건설"},

    # ── 월배당 ETF ─────────────────────────────────────────────────────────
    {"구분": "월배당 ETF", "섹터": "금리형",             "ticker": "459580.KS", "name": "KODEX CD금리액티브(합성)"},
    {"구분": "월배당 ETF", "섹터": "국내 단기채",        "ticker": "214980.KS", "name": "KODEX 단기채권PLUS"},
    {"구분": "월배당 ETF", "섹터": "미국 장기채",        "ticker": "453850.KS", "name": "ACE 미국30년국채액티브(H)"},
    {"구분": "월배당 ETF", "섹터": "장기채 커버드콜",    "ticker": "476550.KS", "name": "TIGER 미국30년국채커버드콜액티브(H)"},
    {"구분": "월배당 ETF", "섹터": "국내 리츠",          "ticker": "329200.KS", "name": "TIGER 리츠부동산인프라"},
    {"구분": "월배당 ETF", "섹터": "국내 고배당",        "ticker": "161510.KS", "name": "PLUS 고배당주"},
    {"구분": "월배당 ETF", "섹터": "은행 고배당",        "ticker": "466940.KS", "name": "TIGER 은행고배당플러스TOP10"},
    {"구분": "월배당 ETF", "섹터": "미국 배당",          "ticker": "458730.KS", "name": "TIGER 미국배당다우존스"},
    {"구분": "월배당 ETF", "섹터": "미국 배당 커버드콜", "ticker": "458760.KS", "name": "TIGER 미국배당다우존스타겟커버드콜2호"},
    {"구분": "월배당 ETF", "섹터": "나스닥100 커버드콜", "ticker": "486290.KS", "name": "TIGER 미국나스닥100타겟데일리커버드콜"},
    {"구분": "월배당 ETF", "섹터": "S&P500 커버드콜",    "ticker": "482730.KS", "name": "TIGER 미국S&P500타겟데일리커버드콜"},
    {"구분": "월배당 ETF", "섹터": "KOSPI200 커버드콜",  "ticker": "498400.KS", "name": "KODEX 200타겟위클리커버드콜"},
    {"구분": "월배당 ETF", "섹터": "미국 테크 커버드콜", "ticker": "474220.KS", "name": "TIGER 미국테크TOP10타겟커버드콜"},
    {"구분": "월배당 ETF", "섹터": "금 커버드콜",          "ticker": "0022T0.KS", "name": "SOL 국제금커버드콜액티브"},

    # ── 국내상장 대표 ETF ───────────────────────────────────────────────────
    {"구분": "국내상장 대표 ETF", "섹터": "KOSPI200 대형",  "ticker": "102110.KS", "name": "TIGER 200"},
    {"구분": "국내상장 대표 ETF", "섹터": "미국 S&P500",    "ticker": "360750.KS", "name": "TIGER 미국S&P500"},
    {"구분": "국내상장 대표 ETF", "섹터": "미국 나스닥100", "ticker": "133690.KS", "name": "TIGER 미국나스닥100"},
    {"구분": "국내상장 대표 ETF", "섹터": "인도 Nifty50",   "ticker": "453870.KS", "name": "TIGER 인도니프티50"},
    {"구분": "국내상장 대표 ETF", "섹터": "일본 Nikkei225", "ticker": "241180.KS", "name": "TIGER 일본니케이225"},
    {"구분": "국내상장 대표 ETF", "섹터": "중국 CSI300",    "ticker": "192090.KS", "name": "TIGER 차이나CSI300"},
    {"구분": "국내상장 대표 ETF", "섹터": "미국 반도체",    "ticker": "381180.KS", "name": "TIGER 미국필라델피아반도체나스닥"},
    {"구분": "국내상장 대표 ETF", "섹터": "중국 전기차",    "ticker": "371460.KS", "name": "TIGER 차이나전기차SOLACTIVE"},
    {"구분": "국내상장 대표 ETF", "섹터": "글로벌 AI",      "ticker": "456600.KS", "name": "TIMEFOLIO 글로벌AI인공지능액티브"},
    {"구분": "국내상장 대표 ETF", "섹터": "헬스케어",       "ticker": "143860.KS", "name": "TIGER 헬스케어"},
    {"구분": "국내상장 대표 ETF", "섹터": "종합채권",       "ticker": "273130.KS", "name": "KODEX 종합채권(AA-이상)액티브"},
    {"구분": "국내상장 대표 ETF", "섹터": "머니마켓",       "ticker": "488770.KS", "name": "KODEX 머니마켓액티브"},

    # ── 글로벌 ─────────────────────────────────────────────────────────────
    {"구분": "글로벌", "섹터": "미국 나스닥",        "ticker": "QQQ",       "name": "Invesco QQQ Trust"},
    {"구분": "글로벌", "섹터": "미국 S&P500",        "ticker": "VOO",       "name": "Vanguard S&P 500 ETF"},
    {"구분": "글로벌", "섹터": "미국 다우존스",      "ticker": "DIA",       "name": "SPDR Dow Jones Industrial Average ETF"},
    {"구분": "글로벌", "섹터": "일본",               "ticker": "EWJ",       "name": "iShares MSCI Japan ETF"},
    {"구분": "글로벌", "섹터": "캐나다",             "ticker": "EWC",       "name": "iShares MSCI Canada ETF"},
    {"구분": "글로벌", "섹터": "한국",               "ticker": "EWY",       "name": "iShares MSCI South Korea ETF"},
    {"구분": "글로벌", "섹터": "대만",               "ticker": "EWT",       "name": "iShares MSCI Taiwan ETF"},
    {"구분": "글로벌", "섹터": "홍콩",               "ticker": "EWH",       "name": "iShares MSCI Hong Kong ETF"},
    {"구분": "글로벌", "섹터": "중국",               "ticker": "MCHI",      "name": "iShares MSCI China ETF"},
    {"구분": "글로벌", "섹터": "인도",               "ticker": "FLIN",      "name": "Franklin FTSE India ETF"},
    {"구분": "글로벌", "섹터": "글로벌AI전력인프라", "ticker": "491010.KS", "name": "TIGER 글로벌AI전력인프라액티브"},
    {"구분": "글로벌", "섹터": "미국AI전력인프라",   "ticker": "487230.KS", "name": "KODEX 미국AI전력핵심인프라"},
    {"구분": "글로벌", "섹터": "우라늄/원전",        "ticker": "URA",       "name": "Global X Uranium ETF"},
    {"구분": "글로벌", "섹터": "브라질",             "ticker": "EWZ",       "name": "iShares MSCI Brazil ETF"},
    {"구분": "글로벌", "섹터": "멕시코",             "ticker": "EWW",       "name": "iShares MSCI Mexico ETF"},
    {"구분": "글로벌", "섹터": "사우디",             "ticker": "KSA",       "name": "iShares MSCI Saudi Arabia ETF"},
    {"구분": "글로벌", "섹터": "베트남",             "ticker": "VNM",       "name": "VanEck Vietnam ETF"},
    {"구분": "글로벌", "섹터": "유럽",              "ticker": "VGK",       "name": "Vanguard FTSE Europe ETF"},

    # ── 매크로 ─────────────────────────────────────────────────────────────
    {"구분": "매크로", "섹터": "금",            "ticker": "IAU",       "name": "iShares Gold Trust"},
    {"구분": "매크로", "섹터": "은(Silver)",    "ticker": "SLV",       "name": "iShares Silver Trust"},       # 산업재 수요+안전자산 혼합
    {"구분": "매크로", "섹터": "원유",          "ticker": "USO",       "name": "United States Oil Fund"},     # 경기/인플레 바로미터
    {"구분": "매크로", "섹터": "한국 금현물",   "ticker": "411060.KS", "name": "ACE KRX금현물"},
    {"구분": "매크로", "섹터": "미국 장기채",   "ticker": "TLT",       "name": "iShares 20+ Year Treasury Bond ETF"},
    {"구분": "매크로", "섹터": "비트코인",      "ticker": "IBIT",      "name": "iShares Bitcoin Trust"},     # 위험자산 선행지표
    {"구분": "매크로", "섹터": "미국 달러",     "ticker": "UUP",       "name": "Invesco DB US Dollar Index Bullish Fund"},
    {"구분": "매크로", "섹터": "미국 단기채",   "ticker": "SHV",       "name": "iShares Short Treasury Bond ETF"},  # 현금 대기 자금
    # 위험선호 선행지표 — 상승=리스크온, 하락=리스크오프
    {"구분": "매크로", "섹터": "하이일드채권",  "ticker": "HYG",       "name": "iShares High Yield Corporate Bond ETF"},
    # 공포지수 — 점수 해석 주의: 상승=공포(리스크오프), 하강=안도(리스크온)
    {"구분": "매크로", "섹터": "공포지수(VIX)", "ticker": "^VIX",      "name": "CBOE Volatility Index"},
]

IMAGE_THEME_GROUPS = [
    {
        "theme": "전력·에너지 인프라",
        # 기존 'AI 에너지·전력' + 'AI 전력망·전력기기' 통합 — 중복 하위테마·종목 정리
        # 재생에너지/원전/ESS/변압기/케이블/그리드/DC냉각/건설을 하나의 밸류체인으로 관리
        "groups": [
            ("원전·SMR", [
                ("두산에너빌리티", "034020.KS"), ("한전기술", "052690.KS"),
                ("우리기술", "032820.KQ"), ("비에이치아이", "083650.KQ"),
            ]),
            ("재생에너지 (태양광·풍력)", [
                ("HD현대에너지솔루션", "322000.KS"), ("OCI홀딩스", "010060.KS"),
                ("한화솔루션", "009830.KS"), ("씨에스윈드", "112610.KS"),
                ("SK이터닉스", "475150.KS"),
            ]),
            ("ESS·배터리저장", [
                ("삼성SDI", "006400.KS"), ("LG에너지솔루션", "373220.KS"),
                ("서진시스템", "178320.KQ"), ("한중엔시에스", "107640.KQ"),
                ("두산퓨얼셀", "336260.KS"),
            ]),
            ("변압기·전력기기 (국내)", [
                ("HD현대일렉트릭", "267260.KS"), ("LS ELECTRIC", "010120.KS"),
                ("효성중공업", "298040.KS"), ("산일전기", "062040.KS"),
            ]),
            ("전력기기 (글로벌)", [
                ("GE버노바", "GEV"), ("이튼", "ETN"),
                ("에머슨일렉트릭", "EMR"), ("허니웰", "HON"),
            ]),
            ("케이블·전선", [
                ("대한전선", "001440.KS"), ("일진전기", "103590.KS"),
                ("가온전선", "000500.KS"), ("LS에코에너지", "229640.KS"),
            ]),
            ("스마트그리드·전력관리", [
                ("지투파워", "388050.KQ"), ("그리드위즈", "453450.KQ"),
                ("LS ELECTRIC", "010120.KS"),
            ]),
            ("DC 전력·냉각", [
                ("버티브", "VRT"), ("이튼", "ETN"),
                ("엔벤트", "NVT"), ("캐리어글로벌", "CARR"),
                ("GST", "083450.KQ"), ("유니셈", "036200.KQ"), ("SNT에너지", "100840.KS"),
            ]),
            ("송전망·인프라 시공 (글로벌)", [
                ("퀀타서비스", "PWR"), ("MYR그룹", "MYRG"),
            ]),
            ("가스터빈·LNG 발전", [
                ("두산에너빌리티", "034020.KS"), ("비에이치아이", "083650.KQ"),
                ("한국가스공사", "036460.KS"), ("지엔씨에너지", "119850.KQ"),
            ]),
            ("EPC·건설", [
                ("현대건설", "000720.KS"), ("삼성E&A", "028050.KS"),
                ("대우건설", "047040.KS"), ("DL이앤씨", "375500.KS"),
            ]),
        ],
    },
    {
        "theme": "글로벌 원전·SMR",
        "groups": [
            ("전력 유틸리티", [
                ("컨스텔레이션에너지", "CEG"), ("비스트라", "VST"),
                ("넥스트에라에너지", "NEE"), ("듀크에너지", "DUK"),
                ("서던컴퍼니", "SO"), ("도미니언에너지", "D"),
                ("탈렌에너지", "TLN"),
            ]),
            ("SMR 개발사", [
                ("뉴스케일파워", "SMR"), ("오클로", "OKLO"),
                ("롤스로이스홀딩스", "RYCEY"),  # 수정: RR.L(런던 상장) → RYCEY(뉴욕 ADR)
            ]),
            ("원전 공급망", [("BWX테크놀로지스", "BWXT"), ("카메코", "CCJ"), ("두산에너빌리티", "034020.KS")]),
            ("우라늄/연료", [("카메코", "CCJ"), ("센트러스에너지", "LEU"), ("에너지퓨얼스", "UUUU")]),
        ],
    },
    {
        "theme": "미국 AI·빅테크",
        # 기존 '빅테크·AI 인프라' + '나스닥 AI 반도체' 통합 — 중복 종목 정리
        # 반도체 코어 → 파운드리 → 클라우드 → 서버 → DC 인프라 밸류체인으로 구성
        "groups": [
            ("AI 반도체 코어", [
                ("엔비디아", "NVDA"), ("AMD", "AMD"),
                ("브로드컴", "AVGO"), ("마벨", "MRVL"),
            ]),
            ("파운드리·인터커넥트", [
                ("TSMC", "TSM"), ("ASML", "ASML"),
                ("아스테라랩스", "ALAB"), ("크레도테크", "CRDO"),
            ]),
            ("반도체 장비", [
                ("어플라이드머티리얼즈", "AMAT"), ("램리서치", "LRCX"),
            ]),
            ("메모리·CPU", [
                ("마이크론", "MU"), ("인텔", "INTC"),
            ]),
            ("클라우드·AI 플랫폼", [
                ("마이크로소프트", "MSFT"), ("아마존", "AMZN"),
                ("알파벳", "GOOGL"), ("메타", "META"),
            ]),
            ("소비자·서비스 생태계", [
                ("애플", "AAPL"), ("넷플릭스", "NFLX"),
                ("오라클", "ORCL"), ("IBM", "IBM"),
            ]),
            ("서버·네트워크 인프라", [
                ("슈퍼마이크로", "SMCI"), ("델", "DELL"), ("HPE", "HPE"),
                ("아리스타", "ANET"), ("시스코", "CSCO"),
            ]),
            ("AI 데이터·분석", [
                ("팔란티어", "PLTR"), ("스노우플레이크", "SNOW"),
                ("데이터독", "DDOG"), ("ServiceNow", "NOW"),
                ("앱러빈", "APP"),
            ]),
            ("AI 소프트웨어·사이버보안", [
                ("오라클", "ORCL"), ("팔로알토네트웍스", "PANW"),
                ("크라우드스트라이크", "CRWD"), ("지스케일러", "ZS"),
                ("클라우드플레어", "NET"),
            ]),
            ("AI 모빌리티·로보틱스", [
                ("테슬라", "TSLA"), ("우버", "UBER"), ("모바일아이", "MBLY"),
            ]),
            ("DC 전력·냉각", [
                ("버티브", "VRT"), ("이튼", "ETN"), ("GE버노바", "GEV"),
            ]),
        ],
    },
    {
        "theme": "미국 헬스케어·바이오텍",
        # IBB·XLV ETF가 MONEY_FLOW_UNIVERSE에 있지만 개별 종목 테마가 없어서 신규 추가
        # 빅파마 / 바이오텍 / 의료기기 / 임상·CRO / 보험·서비스 5축 구성
        "groups": [
            ("빅파마 (Big Pharma)", [
                ("일라이릴리", "LLY"), ("애브비", "ABBV"),
                ("존슨앤존슨", "JNJ"), ("화이자", "PFE"), ("머크", "MRK"),
            ]),
            ("바이오텍", [
                ("모더나", "MRNA"), ("리제네론", "REGN"),
                ("길리어드", "GILD"), ("바이오젠", "BIIB"), ("버텍스", "VRTX"),
            ]),
            ("의료기기", [
                ("인튜이티브서지컬", "ISRG"), ("스트라이커", "SYK"),
                ("메드트로닉", "MDT"), ("에드워즈라이프", "EW"),
            ]),
            ("임상연구·CRO·장비", [
                ("써모피셔", "TMO"), ("아이콘", "ICLR"),
                ("찰스리버", "CRL"), ("Agilent", "A"),
            ]),
            ("의료보험·서비스", [
                ("유나이티드헬스", "UNH"), ("CVS헬스", "CVS"), ("시그나", "CI"),
            ]),
        ],
    },
    {
        "theme": "국내 AI 반도체·소부장",
        "groups": [
            ("HBM/메모리", [("SK하이닉스", "000660.KS"), ("삼성전자", "005930.KS")]),
            ("팹리스/설계", [
                ("가온칩스", "399720.KQ"), ("텔레칩스", "054450.KQ"),
                ("어보브반도체", "102120.KQ"), ("LX세미콘", "108320.KS"),
            ]),
            ("기판/PCB", [
                ("대덕전자", "353200.KS"), ("심텍", "222800.KQ"),
                ("티엘비", "356860.KQ"), ("해성디에스", "195870.KS"),
            ]),
            ("소재/케미칼", [
                ("솔브레인", "357780.KQ"), ("한솔케미칼", "014680.KS"),
                ("동진쎄미켐", "005290.KQ"), ("원익머트리얼즈", "104830.KQ"),
                ("덕산네오룩스", "213420.KQ"),
            ]),
            ("블랭크마스크", [("에스앤에스텍", "101490.KQ")]),
            ("전공정 장비", [
                ("HPSP", "403870.KQ"), ("유진테크", "084370.KQ"),
                ("테스", "095610.KQ"), ("케이씨텍", "281820.KS"),
                ("원익IPS", "240810.KQ"), ("주성엔지니어링", "036930.KQ"),
            ]),
            ("후공정/패키징", [("한미반도체", "042700.KS"), ("하나마이크론", "067310.KQ"), ("네패스", "033640.KQ")]),
            ("검사/테스트", [
                ("ISC", "095340.KQ"), ("리노공업", "058470.KQ"),
                ("테크윙", "089030.KQ"), ("디아이", "003160.KS"),
                ("티에스이", "131290.KQ"), ("마이크로컨텍솔", "098120.KQ"),
            ]),
            ("후공정 장비", [("한미반도체", "042700.KS"), ("테크윙", "089030.KQ"), ("제우스", "079370.KQ"), ("프로텍", "053610.KQ")]),
            ("전력/아날로그", [("DB하이텍", "000990.KS"), ("아이에이", "038880.KQ"), ("LX세미콘", "108320.KS")]),
            ("냉각/인프라", [("GST", "083450.KQ"), ("유니셈", "036200.KQ"), ("케이엔솔", "053080.KQ")]),
            ("유리기판/신기술", [("SKC", "011790.KS"), ("필옵틱스", "161580.KQ"), ("와이씨켐", "112290.KQ")]),
            ("온디바이스 AI", [("텔레칩스", "054450.KQ"), ("제주반도체", "080220.KQ"), ("어보브반도체", "102120.KQ")]),
            ("지주/밸류체인", [("원익홀딩스", "030530.KQ"), ("케이씨", "029460.KS")]),
        ],
    },
    # ── 우주·위성 RF통신 (2026 Space RF 테마, 이미지 기반) ──────────────────
    # 그룹 원칙: 종목당 1개 그룹 소속 — 중복 없음
    {
        "theme": "우주·위성 RF통신",
        "groups": [
            # 위성 서비스·발사 (고베타 성장형)
            ("위성 서비스·발사 (성장형)", [
                ("AST스페이스모바일", "ASTS"),
                ("로켓랩", "RKLB"),
                ("플래닛랩스", "PL"),
                ("블랙스카이", "BKSY"),
            ]),
            # 안정형 위성 인프라·시스템
            ("위성 인프라·시스템 (안정형)", [
                ("이리듐", "IRDM"),
                ("글로벌스타", "GSAT"),
                ("비아샛", "VSAT"),
                ("크라토스", "KTOS"),
                ("키사이트", "KEYS"),
            ]),
            # 방산 프라임 (주파수·스펙트럼 확보)
            ("방산 프라임 (주파수·스펙트럼)", [
                ("록히드마틴", "LMT"),
                ("노스롭그루먼", "NOC"),
            ]),
            # RF GaN 반도체 부품
            ("RF GaN 반도체 부품", [
                ("MACOM", "MTSI"),
                ("Qorvo", "QRVO"),
                ("STMicro", "STM"),
            ]),
            # 한국 체계종합·방산
            ("한국 체계종합·방산", [
                ("한화시스템", "272210.KS"),
                ("LIG넥스원", "079550.KS"),
                ("한화에어로스페이스", "012450.KS"),
            ]),
            # 한국 안테나·RF부품 순수주
            ("한국 안테나·RF부품", [
                ("인텔리안테크", "189300.KQ"),
                ("RFHIC", "218410.KQ"),
            ]),
            # 한국 위성단말·지상국·발사 중소형
            ("한국 위성단말·지상국·발사", [
                ("AP위성", "211270.KQ"),
                ("제노코", "361390.KQ"),
                ("컨텍", "451760.KQ"),
                ("쎄트렉아이", "099320.KQ"),
                ("이노스페이스", "462350.KQ"),
            ]),
        ],
    },
    # ── 우주항공·방산 (순수 방산·항공 집중) ────────────────────────────────
    {
        "theme": "우주항공·방산",
        "groups": [
            ("한국 항공엔진/기체", [
                ("한화에어로스페이스", "012450.KS"),
                ("한국항공우주", "047810.KS"),
                ("켄코아에어로스페이스", "274090.KQ"),
            ]),
            ("한국 유도무기·미사일", [
                ("LIG넥스원", "079550.KS"),
                ("한화에어로스페이스", "012450.KS"),
                ("한화시스템", "272210.KS"),
            ]),
            ("한국 레이더·전자전", [
                ("한화시스템", "272210.KS"),
                ("빅텍", "065450.KQ"),
                ("휴니드", "005870.KS"),
            ]),
            ("한국 전투기·항공기", [
                ("한국항공우주", "047810.KS"),
                ("대한항공", "003490.KS"),
            ]),
            ("한국 드론·UAM", [
                ("퍼스텍", "010820.KS"),
                ("네온테크", "306620.KQ"),
                ("제노코", "361390.KQ"),
            ]),
            ("한국 함정·지상전력", [
                ("HD현대중공업", "329180.KS"),
                ("한화오션", "042660.KS"),
                ("HJ중공업", "097230.KS"),
                ("현대로템", "064350.KS"),
            ]),
            ("한국 탄약·화약", [
                ("풍산", "103140.KS"),
                ("한화", "000880.KS"),
                ("SNT다이내믹스", "003570.KS"),
            ]),
            ("미국 방산 프라임", [
                ("록히드마틴", "LMT"),
                ("RTX", "RTX"),
                ("노스롭그루먼", "NOC"),
                ("제너럴다이내믹스", "GD"),
                ("L3해리스", "LHX"),
            ]),
            ("미국 무인·드론", [("크라토스", "KTOS"), ("에어로바이론먼트", "AVAV")]),
            ("미국 항공기", [("보잉", "BA"), ("텍스트론", "TXT")]),
        ],
    },
    {
        "theme": "휴머노이드·로봇",
        "groups": [
            ("한국 협동로봇", [("두산로보틱스", "454910.KS"), ("레인보우로보틱스", "277810.KQ"), ("뉴로메카", "348340.KQ")]),
            ("한국 휴머노이드 핵심", [("레인보우로보틱스", "277810.KQ"), ("로보티즈", "108490.KQ"), ("두산로보틱스", "454910.KS")]),
            ("한국 감속기/모터", [("에스피지", "058610.KQ"), ("해성티피씨", "059270.KQ"), ("에스비비테크", "389500.KQ")]),
            ("한국 액추에이터/제어", [("로보티즈", "108490.KQ"), ("아진엑스텍", "059120.KQ"), ("우림피티에스", "101170.KQ")]),
            ("한국 스마트팩토리", [("LS ELECTRIC", "010120.KS"), ("알에스오토메이션", "140670.KQ"), ("코윈테크", "282880.KQ")]),
            ("한국 물류자동화", [("현대무벡스", "319400.KQ"), ("티로보틱스", "117730.KQ"), ("유진로봇", "056080.KQ")]),
            ("한국 자율주행/AMR", [("유진로봇", "056080.KQ"), ("클로봇", "466100.KQ"), ("티라유텍", "322180.KQ")]),
            ("한국 비전/센서", [("고영", "098460.KQ"), ("아이쓰리시스템", "214430.KQ"), ("퓨런티어", "370090.KQ")]),
            ("한국 로봇 AI/SW", [("솔트룩스", "304100.KQ"), ("마음AI", "377480.KQ"), ("이스트소프트", "047560.KQ")]),
            ("한국 서비스로봇", [("로보로보", "215100.KQ"), ("클로봇", "466100.KQ"), ("에브리봇", "270660.KQ")]),
            ("한국 정밀부품", [("삼익THK", "004380.KS"), ("대동기어", "008830.KQ"), ("에스피지", "058610.KQ")]),
            ("한국 장비 수혜", [("티로보틱스", "117730.KQ"), ("유일로보틱스", "388720.KQ"), ("에브리봇", "270660.KQ")]),
            ("글로벌 휴머노이드/AI", [("테슬라", "TSLA"), ("엔비디아", "NVDA")]),
            ("글로벌 물류/수술", [("심보틱", "SYM"), ("아마존", "AMZN"), ("인튜이티브서지컬", "ISRG")]),
            ("글로벌 자율주행", [("모바일아이", "MBLY"), ("우버", "UBER"), ("테슬라", "TSLA")]),
            ("글로벌 공장 자동화", [("허니웰", "HON"), ("록웰오토메이션", "ROK"), ("에머슨일렉트릭", "EMR")]),
        ],
    },
    {
        "theme": "PCB·기판 글로벌",
        # 주의: .T(도쿄) .TW(대만) .VI(비엔나) 티커는 yfinance 지원 불안정.
        # 데이터 부족 시 해당 종목은 "가격부족"으로 표시되며 점수 산정에서 자동 제외됨.
        "groups": [
            ("FC-BGA", [("삼성전기", "009150.KS"), ("IBIDEN", "4062.T"), ("유니마이크론", "3037.TW")]),
            ("ABF 기판", [("IBIDEN", "4062.T"), ("유니마이크론", "3037.TW"), ("난야PCB", "8046.TW"), ("킨서스", "3189.TW")]),
            ("AI 서버 MLB", [("이수페타시스", "007660.KS"), ("TTM테크놀로지스", "TTMI"), ("컴팩", "2313.TW"), ("젠딩테크", "4958.TW")]),
            ("메모리 패키지", [("심텍", "222800.KQ"), ("대덕전자", "353200.KS"), ("코리아써키트", "007810.KS"), ("해성디에스", "195870.KS")]),
            ("모바일/HDI", [("젠딩테크", "4958.TW"), ("컴팩", "2313.TW"), ("유니마이크론", "3037.TW"), ("비에이치", "090460.KS")]),
            ("FPCB/연성기판", [("비에이치", "090460.KS"), ("인터플렉스", "051370.KQ"), ("젠딩테크", "4958.TW")]),
            ("자동차 전장", [("해성디에스", "195870.KS"), ("삼성전기", "009150.KS"), ("AT&S", "ATS.VI"), ("메이코", "6787.T")]),
            ("일본 선두주", [("IBIDEN", "4062.T"), ("메이코", "6787.T")]),
            ("대만 선두주", [("유니마이크론", "3037.TW"), ("난야PCB", "8046.TW"), ("킨서스", "3189.TW"), ("컴팩", "2313.TW"), ("젠딩테크", "4958.TW")]),
            ("유럽/미국 축", [("AT&S", "ATS.VI"), ("TTM테크놀로지스", "TTMI")]),
        ],
    },
    {
        "theme": "전자부품·MLCC",
        "groups": [
            ("MLCC·콘덴서", [
                ("삼성전기", "009150.KS"), ("삼화콘덴서", "001820.KS"),
                ("코칩", "126730.KQ"), ("아모텍", "052710.KQ"),
            ]),
            ("전장·카메라모듈", [
                ("LG이노텍", "011070.KS"), ("엠씨넥스", "097520.KS"),
                ("파트론", "091700.KQ"), ("나무가", "190510.KQ"),
            ]),
            ("전자소재·부품", [
                ("대주전자재료", "078600.KQ"), ("나노신소재", "121600.KQ"),
                ("아비코전자", "036010.KQ"), ("비에이치", "090460.KS"),
            ]),
        ],
    },
    {
        "theme": "포토닉스·광통신",
        "groups": [
            ("포토닉 소재/기판", [("코닝", "GLW"), ("라이트웨이브로직", "LWLG"), ("AXT", "AXTI"), ("알버말", "ALB")]),
            ("패키징/조립", [("파브리넷", "FN"), ("암코", "AMKR"), ("TSMC", "TSM"), ("글로벌파운드리스", "GFS")]),
            ("레이저/광원", [("루멘텀", "LITE"), ("코히런트", "COHR"), ("IPG포토닉스", "IPGP")]),
            ("광부품/트랜시버", [("어플라이드옵토", "AAOI")]),
            ("포토닉 집적회로", [("MACOM", "MTSI"), ("POET", "POET"), ("브로드컴", "AVGO"), ("마벨", "MRVL"), ("크레도", "CRDO")]),
            ("테스트/계측", [("비아비", "VIAV"), ("AEHR", "AEHR"), ("MKS", "MKSI")]),
            ("광네트워킹", [("시에나", "CIEN"), ("시스코", "CSCO")]),
            ("데이터센터 연결", [("브로드컴", "AVGO"), ("마벨", "MRVL"), ("크레도", "CRDO")]),
            ("실리콘 포토닉스", [("라이트웨이브로직", "LWLG"), ("브로드컴", "AVGO"), ("마벨", "MRVL")]),
        ],
    },

    # ── 이하 judal.co.kr 테마 데이터 기반 추가 (2026-05) ──────────────────────
    {
        "theme": "2차전지 밸류체인",
        # 출처: judal themeIdx=39(코어), 214(장비), 560(소재부품)
        "groups": [
            ("셀 메이커", [
                ("LG에너지솔루션", "373220.KS"), ("삼성SDI", "006400.KS"),
                ("SK이노베이션", "096770.KS"), ("에코프로비엠", "247540.KQ"),
                ("에코프로", "086520.KQ"), ("롯데에너지머티리얼즈", "020150.KS"),
            ]),
            ("양극재", [
                ("포스코퓨처엠", "003670.KS"), ("에코프로비엠", "247540.KQ"),
                ("엘앤에프", "066970.KS"), ("코스모신소재", "005070.KS"),
                ("에코프로머티", "450080.KS"),
            ]),
            ("음극재·전해질", [
                ("포스코퓨처엠", "003670.KS"), ("천보", "278280.KS"),
                ("엔켐", "348370.KQ"), ("솔브레인", "357780.KQ"),
            ]),
            ("동박·알루미늄박", [
                ("롯데에너지머티리얼즈", "020150.KS"), ("SKC", "011790.KS"),
                ("고려아연", "010130.KS"),
            ]),
            ("분리막·케이스", [
                ("SK아이이테크놀로지", "361610.KS"), ("한솔케미칼", "014680.KS"),
                ("PI첨단소재", "178920.KS"),
            ]),
            ("장비", [
                ("피엔티", "137400.KQ"), ("에스에프에이", "056190.KQ"),
                ("원익피앤이", "217820.KS"), ("하나기술", "299030.KQ"),
                ("코윈테크", "282880.KQ"), ("씨아이에스", "222080.KQ"),
            ]),
        ],
    },
    {
        "theme": "조선·해양",
        # 출처: judal themeIdx=27(조선), 647(조선기자재)
        "groups": [
            ("조선 대형 3사", [
                ("HD현대중공업", "329180.KS"), ("한화오션", "042660.KS"),
                ("삼성중공업", "010140.KS"), ("HJ중공업", "097230.KS"),
            ]),
            ("엔진·추진", [
                ("HD현대마린엔진", "071970.KS"), ("한화엔진", "082740.KS"),
                ("STX엔진", "077970.KS"), ("HD현대마린솔루션", "443060.KS"),
            ]),
            ("LNG·화물창 소재", [
                ("동성화인텍", "033500.KQ"), ("한국카본", "017960.KS"),
                ("성광벤드", "014620.KQ"), ("태광", "023160.KQ"),
            ]),
            ("해양 인프라·구조물", [
                ("SK오션플랜트", "100090.KS"), ("세진중공업", "075580.KQ"),
                ("태웅", "044490.KS"),
            ]),
            ("기자재·배관", [
                ("하이록코리아", "013030.KQ"), ("비엠티", "086670.KQ"),
                ("오리엔탈정공", "014940.KQ"), ("대양전기공업", "108380.KQ"),
            ]),
        ],
    },
    {
        "theme": "바이오·제약",
        # 출처: judal themeIdx=9(바이오), 225(제약), 635(바이오AI)
        "groups": [
            ("CDMO·위탁생산", [
                ("삼성바이오로직스", "207940.KS"), ("셀트리온", "068270.KS"),
                ("알테오젠", "196170.KQ"), ("프레스티지바이오파마", "950210.KS"),
            ]),
            ("신약 파이프라인", [
                ("HLB", "028300.KQ"), ("에이비엘바이오", "298380.KQ"),
                ("SK바이오팜", "326030.KS"), ("한올바이오파마", "009420.KS"),
                ("보로노이", "310210.KQ"),
            ]),
            ("제약 대형주", [
                ("유한양행", "000100.KS"), ("한미약품", "128940.KS"),
                ("에스티팜", "237690.KQ"), ("종근당", "185750.KS"),
                ("대웅제약", "069620.KS"), ("녹십자", "006280.KS"),
            ]),
            ("진단·백신", [
                ("씨젠", "096530.KQ"), ("SK바이오사이언스", "302440.KS"),
                ("바이오니아", "064550.KQ"),
            ]),
        ],
    },
    {
        "theme": "K-뷰티·소비재",
        # 출처: judal themeIdx=50(화장품), 120(패션)
        "groups": [
            ("화장품 대형 브랜드", [
                ("아모레퍼시픽", "090430.KS"), ("LG생활건강", "051900.KS"),
                ("에이피알", "278470.KS"),
            ]),
            ("OEM·ODM", [
                ("한국콜마", "161890.KS"), ("코스맥스", "192820.KS"),
                ("씨앤씨인터내셔널", "352480.KQ"), ("콜마홀딩스", "024720.KS"),
            ]),
            ("인디·중소 브랜드", [
                ("마녀공장", "439090.KQ"), ("클리오", "237880.KQ"),
                ("잇츠한불", "226320.KS"), ("네오팜", "092730.KQ"),
            ]),
            ("패션·라이프스타일", [
                ("F&F", "383220.KS"), ("영원무역", "111770.KS"),
                ("한세실업", "105630.KS"), ("젝시믹스", "337930.KQ"),
            ]),
        ],
    },
    {
        "theme": "한국 금융",
        "groups": [
            ("은행", [
                ("KB금융", "105560.KS"), ("신한지주", "055550.KS"),
                ("하나금융지주", "086790.KS"), ("우리금융지주", "316140.KS"),
                ("BNK금융지주", "138930.KS"), ("기업은행", "024110.KS"),
            ]),
            ("증권", [
                ("미래에셋증권", "006800.KS"), ("삼성증권", "016360.KS"),
                ("키움증권", "039490.KS"), ("한국금융지주", "071050.KS"),
                ("NH투자증권", "005940.KS"),
            ]),
            ("보험", [
                ("삼성생명", "032830.KS"), ("삼성화재", "000810.KS"),
                ("현대해상", "001450.KS"), ("DB손해보험", "005830.KS"),
                ("한화생명", "088350.KS"),
            ]),
            ("카드·핀테크", [
                ("삼성카드", "029780.KS"), ("카카오페이", "377300.KS"),
                ("카카오뱅크", "323410.KS"), ("케이뱅크", "279570.KS"),
            ]),
        ],
    },
    {
        "theme": "미국 금융·핀테크",
        "groups": [
            ("미국 대형 은행", [
                ("JP모건", "JPM"), ("뱅크오브아메리카", "BAC"),
                ("웰스파고", "WFC"), ("골드만삭스", "GS"), ("모건스탠리", "MS"),
            ]),
            ("핀테크·결제", [
                ("비자", "V"), ("마스터카드", "MA"),
                ("페이팔", "PYPL"), ("블록", "SQ"), ("어펌", "AFRM"),
            ]),
            ("보험·자산운용", [
                ("버크셔해서웨이", "BRK-B"), ("블랙록", "BLK"),
                ("찰스슈왑", "SCHW"), ("아메리칸익스프레스", "AXP"),
            ]),
        ],
    },
    {
        "theme": "글로벌 인프라·산업재",
        "groups": [
            ("미국 산업재 대형주", [
                ("캐터필러", "CAT"), ("디어앤컴퍼니", "DE"),
                ("허니웰", "HON"), ("GE에어로스페이스", "GE"), ("RTX", "RTX"),
            ]),
            ("구리·광물 소재", [
                ("프리포트맥모란", "FCX"), ("뉴몬트", "NEM"),
                ("뉴코", "NUE"), ("스틸다이나믹스", "STLD"),
            ]),
            ("건설·주택", [
                ("DR호튼", "DHI"), ("레나", "LEN"),
                ("풀티홈", "PHM"), ("톨브라더스", "TOL"),
            ]),
        ],
    },
]

IMAGE_THEME_UNIVERSE = [
    {"테마": tg["theme"], "하위테마": sub, "name": name, "ticker": ticker}
    for tg in IMAGE_THEME_GROUPS
    for sub, items in tg["groups"]
    for name, ticker in items
]

# 테마별 메타데이터: 설명, 지역 태그, 관련 ETF 벤치마크
IMAGE_THEME_META: dict[str, dict] = {
    "전력·에너지 인프라": {
        "tag": "🇰🇷 국내+글로벌",
        "desc": "원전·재생에너지·ESS·변압기·케이블·스마트그리드·DC냉각 전력 밸류체인",
        "etf": "487240.KS",   # KODEX AI전력핵심설비
    },
    "글로벌 원전·SMR": {
        "tag": "🇺🇸 미국+글로벌",
        "desc": "미국 원전 유틸리티, SMR 개발사, 우라늄/연료 공급망",
        "etf": "URA",
    },
    "미국 AI·빅테크": {
        "tag": "🇺🇸 미국",
        "desc": "AI 반도체→파운드리→클라우드→서버→DC 전력·냉각 풀 밸류체인",
        "etf": "QQQ",
    },
    "국내 AI 반도체·소부장": {
        "tag": "🇰🇷 국내",
        "desc": "HBM/메모리, 팹리스, 기판/PCB, 소재, 전공정·후공정 장비 국내 공급망",
        "etf": "396500.KS",   # TIGER 반도체TOP10
    },
    "우주·위성 RF통신": {
        "tag": "🛰️ 우주RF",
        "desc": "D2D/NTN 직통위성, LEO 발사체, RF GaN 부품, 지상국·안테나 — 2026 핵심 성장 테마",
        "etf": "UFO",         # Procure Space ETF
    },
    "우주항공·방산": {
        "tag": "🇰🇷+🇺🇸",
        "desc": "한국 방산(항공엔진·유도무기·함정·레이더)과 미국 방산 프라임·드론·항공기",
        "etf": "449450.KS",   # PLUS K방산
    },
    "휴머노이드·로봇": {
        "tag": "🇰🇷+🇺🇸",
        "desc": "협동·휴머노이드 로봇, 감속기·액추에이터, 스마트팩토리, 글로벌 자동화",
        "etf": "BOTZ",
    },
    "PCB·기판 글로벌": {
        "tag": "🌐 글로벌",
        "desc": "FC-BGA·ABF기판, AI 서버 MLB, 메모리 패키지 — 한국·일본·대만·미국 비교",
        "etf": "SOXX",
    },
    "전자부품·MLCC": {
        "tag": "🇰🇷 국내",
        "desc": "MLCC·콘덴서, 전장부품, 카메라모듈, 전자소재 국내 부품 밸류체인",
        "etf": "139260.KS",
    },
    "포토닉스·광통신": {
        "tag": "🇺🇸 미국",
        "desc": "데이터센터 광연결, 실리콘 포토닉스, 레이저/트랜시버, AI 인터커넥트",
        "etf": "CIBR",
    },
    "2차전지 밸류체인": {
        "tag": "🇰🇷 국내",
        "desc": "셀 메이커→양극재→음극재→동박→분리막→장비 국내 배터리 풀 밸류체인",
        "etf": "305540.KS",   # TIGER 2차전지테마
    },
    "조선·해양": {
        "tag": "🇰🇷 국내",
        "desc": "대형 조선 3사, 엔진·추진, LNG 화물창 소재, 해양 구조물, 기자재",
        "etf": "494670.KS",   # TIGER 조선TOP10
    },
    "바이오·제약": {
        "tag": "🇰🇷 국내",
        "desc": "CDMO/위탁생산, 신약 파이프라인, 대형 제약사, 진단·백신 국내 바이오",
        "etf": "244580.KS",   # KODEX 바이오
    },
    "K-뷰티·소비재": {
        "tag": "🇰🇷 국내",
        "desc": "화장품 대형 브랜드, OEM/ODM, 인디 브랜드, 패션·라이프스타일",
        "etf": "479850.KS",   # HANARO K-뷰티
    },
    "미국 헬스케어·바이오텍": {
        "tag": "🇺🇸 미국",
        "desc": "빅파마, 바이오텍, 의료기기, CRO/임상연구, 의료보험·서비스",
        "etf": "IBB",
    },
    "한국 금융": {
        "tag": "🇰🇷 국내",
        "desc": "국내 4대 금융지주(은행), 대형 증권사, 생명·손해보험, 카드·인터넷은행",
        "etf": "139270.KS",
    },
    "미국 금융·핀테크": {
        "tag": "🇺🇸 미국",
        "desc": "미국 대형 은행·보험·자산운용, 핀테크·결제 플랫폼, 디지털 금융 인프라",
        "etf": "XLF",
    },
    "글로벌 인프라·산업재": {
        "tag": "🇺🇸 미국+글로벌",
        "desc": "미국 산업재 대형주, 구리·광물 소재, 건설·주택, 글로벌 인프라 수혜",
        "etf": "XLI",
    },
}

# ---------------------------------------------------------------------------
# 섹터 클러스터 — 한국/미국 완전 분리 (벤치마크가 달라 혼합 불가)
#
# SECTOR_CLUSTERS_KR : 벤치마크 = KOSPI200  (한국 섹터 RS 기준)
# SECTOR_CLUSTERS_US : 벤치마크 = S&P500    (미국 섹터 RS 기준)
#
# 패널: 각 시장에서 열기점수 상위 3개씩 → 총 6카드 (자동 교체)
# ---------------------------------------------------------------------------

# ── 한국 섹터 클러스터 (KOSPI200 대비 RS) ───────────────────────────────
SECTOR_CLUSTERS_KR: dict[str, list[str]] = {
    # 069500.KS(KODEX200)는 KOSPI200 벤치마크 자체 → RS≈0%이므로 제외
    "AI·반도체":     ["396500.KS", "139260.KS", "381180.KS", "456600.KS"],
    "전력·인프라":   ["487240.KS", "0117V0.KS", "487230.KS", "491010.KS"],
    "원전·우라늄":   ["434730.KS", "433500.KS"],
    "방산·조선":     ["449450.KS", "494670.KS"],
    "K뷰티·콘텐츠": ["266360.KS", "479850.KS", "228790.KS"],
    "바이오":        ["244580.KS", "143860.KS"],
    "금융":          ["139270.KS"],
    "2차전지":       ["305540.KS"],
    "리츠":          ["329200.KS"],
    "에너지·건설":   ["139250.KS", "139220.KS"],
}

# ── 미국 섹터 클러스터 (S&P500 대비 RS) ─────────────────────────────────
SECTOR_CLUSTERS_US: dict[str, list[str]] = {
    "AI·반도체":        ["QQQ", "XLK", "SOXX", "SMH", "BOTZ", "QTUM"],
    "소프트웨어·사이버": ["IGV", "CIBR", "XLC"],
    "전력·인프라":       ["GRID", "PAVE", "ICLN", "XLU"],
    "방산·우주":         ["SHLD", "ITA", "UFO"],
    "바이오·헬스":       ["XLV", "IBB"],
    "금융·핀테크":       ["XLF", "FINX"],
    "소비재":            ["XLY", "XLP"],
    "산업재·원자재":     ["XLI", "XLB", "COPX", "XHB"],
    "에너지":            ["XLE", "USO"],
    "2차전지·EV":        ["LIT"],
    "안전자산·채권":     ["TLT", "IAU", "SLV", "SHV", "HYG"],
}

# 하위 호환 alias (기존 단독 호출 코드용)
SECTOR_CLUSTERS: dict[str, list[str]] = {**SECTOR_CLUSTERS_KR, **SECTOR_CLUSTERS_US}

# 섹터 ETF → 개별 테마 종목 흐름 매핑
# 로테이션 맵에서 주도 ETF 클릭 시 연관 테마로 바로가기
ETF_TO_THEME: dict[str, str] = {
    "UFO":       "우주·위성 RF통신",
    "SHLD":      "우주항공·방산",
    "ITA":       "우주항공·방산",
    "SOXX":      "국내 AI 반도체·소부장",
    "SMH":       "국내 AI 반도체·소부장",
    "QQQ":       "미국 AI·빅테크",
    "IGV":       "미국 AI·빅테크",
    "XLK":       "미국 AI·빅테크",
    "CIBR":      "미국 AI·빅테크",
    "BOTZ":      "휴머노이드·로봇",
    "PAVE":      "전력·에너지 인프라",
    "GRID":      "전력·에너지 인프라",
    "ICLN":      "전력·에너지 인프라",
    "LIT":       "2차전지 밸류체인",
    "URA":       "글로벌 원전·SMR",
    "IBB":       "미국 헬스케어·바이오텍",
    "396500.KS": "국내 AI 반도체·소부장",
    "139260.KS": "국내 AI 반도체·소부장",
    "305540.KS": "2차전지 밸류체인",
    "434730.KS": "글로벌 원전·SMR",
    "487240.KS": "전력·에너지 인프라",
    "491010.KS": "전력·에너지 인프라",
    "487230.KS": "전력·에너지 인프라",
    "244580.KS": "바이오·제약",
    "479850.KS": "K-뷰티·소비재",
    "494670.KS": "조선·해양",
    "139270.KS": "한국 금융",
    "XLF":       "미국 금융·핀테크",
    "FINX":      "미국 금융·핀테크",
    "XLI":       "글로벌 인프라·산업재",
    "XLB":       "글로벌 인프라·산업재",
    "COPX":      "글로벌 인프라·산업재",
    "XHB":       "글로벌 인프라·산업재",
}


def get_image_theme_names() -> list:
    return [tg["theme"] for tg in IMAGE_THEME_GROUPS]


# ---------------------------------------------------------------------------
# 티커 정규화
# ---------------------------------------------------------------------------

def normalize_money_flow_ticker(ticker: str) -> str:
    """KRX 6자리 제로패딩 정규화.

    주의: 알파벳 포함 코드(0117V0, 0022T0 등)는 이미 6자이므로
    zfill 변환이 발생하지 않으며, yfinance도 해당 코드를 인식하지 못함.
    이런 티커는 MONEY_FLOW_UNIVERSE에서 제거하는 것이 바람직함.
    """
    t = str(ticker).strip().upper()
    if t.endswith(".KS") or t.endswith(".KQ"):
        code, suffix = t.split(".", 1)
        return f"{code.zfill(6)}.{suffix}"
    return t


def _money_flow_suffix(ticker: str) -> str:
    t = str(ticker or "").strip().upper()
    return t.rsplit(".", 1)[-1] if "." in t else ""


def _is_krx_money_flow_ticker(ticker: str) -> bool:
    return _money_flow_suffix(ticker) in ("KS", "KQ")


# ---------------------------------------------------------------------------
# Alpha Vantage 선택적 폴백
# ---------------------------------------------------------------------------

def _fetch_alpha_vantage_ohlc(ticker: str) -> pd.DataFrame:
    """Alpha Vantage에서 단일 티커 OHLCV 취득 (AV_API_KEY 환경변수 필요).

    - 미국 상장 티커 한정: KRX(.KS/.KQ) 및 해외 거래소(.T/.TW/.VI/.L) 제외
    - 무료 티어: 25 calls/day  |  유료: 500+ calls/min
    - yfinance 실패 티커의 폴백으로만 호출됨
    """
    if not _AV_API_KEY:
        return pd.DataFrame()
    suffix = ticker.split(".")[-1] if "." in ticker else ""
    if suffix in _UNRELIABLE_SUFFIXES or suffix in ("KS", "KQ"):
        return pd.DataFrame()
    try:
        import requests  # 선택적 의존성
        url = (
            "https://www.alphavantage.co/query"
            f"?function=TIME_SERIES_DAILY_ADJUSTED&symbol={ticker}"
            "&outputsize=full&datatype=json"
            f"&apikey={_AV_API_KEY}"
        )
        resp = requests.get(url, timeout=15)
        raw = resp.json().get("Time Series (Daily)", {})
        if not raw:
            return pd.DataFrame()
        df = pd.DataFrame.from_dict(raw, orient="index").rename(columns={
            "1. open": "Open", "2. high": "High", "3. low": "Low",
            "4. close": "Close", "5. adjusted close": "Adj Close",
            "6. volume": "Volume",
        })
        df.index = pd.to_datetime(df.index)
        df = df.sort_index()[["Open", "High", "Low", "Close", "Volume"]].astype(float)
        cutoff = pd.Timestamp.now() - pd.DateOffset(years=1)
        return df[df.index >= cutoff]
    except Exception:
        return pd.DataFrame()


# ---------------------------------------------------------------------------
# FinanceDataReader 폴백
# ---------------------------------------------------------------------------

@st.cache_data(ttl=900, show_spinner=False)
def _fetch_fdr_ohlc(ticker: str) -> pd.DataFrame:
    """FinanceDataReader로 단일 티커 OHLCV 취득.

    적용 케이스:
    - .T  (도쿄 TSE): '4062.T'   → fdr 'TSE:4062'
    - .KS/.KQ (KRX) : '0117V0.KS' → fdr '0117V0'  (알파벳 포함 코드 포함)
    - fdr 전용 심볼 : 'VIX', 'US10YT', 'KS11' 등

    설치: pip install finance-datareader
    """
    if not _FDR_AVAILABLE:
        return pd.DataFrame()

    start = (pd.Timestamp.now() - pd.DateOffset(years=1)).strftime("%Y-%m-%d")

    # 거래소 접미사별 fdr 심볼 변환
    if ticker.endswith(".T"):
        fdr_symbol = f"TSE:{ticker[:-2]}"
    elif ticker.endswith(".KS") or ticker.endswith(".KQ"):
        fdr_symbol = ticker.split(".")[0]   # 숫자/알파벳 코드 모두 그대로 사용
    else:
        fdr_symbol = ticker                 # VIX, US10YT 등 fdr 네이티브 심볼

    try:
        df = fdr.DataReader(fdr_symbol, start)
        if df is None or df.empty:
            return pd.DataFrame()

        # fdr 컬럼 정규화 (소문자 → 첫글자 대문자)
        df = df.rename(columns=lambda c: c.capitalize())
        # 'Adj close' 같은 케이스 처리
        if "Close" not in df.columns and "Adj close" in df.columns:
            df = df.rename(columns={"Adj close": "Close"})
        if "Change" in df.columns:
            df = df.drop(columns=["Change"])

        needed = ["Close", "High", "Low"]
        if not all(c in df.columns for c in needed):
            # High/Low 없으면 Close로 채움 (지수/금리 데이터)
            for c in needed:
                if c not in df.columns:
                    df[c] = df.get("Close", np.nan)

        cols = ["Close", "High", "Low"] + (["Volume"] if "Volume" in df.columns else [])
        return df[cols].ffill().dropna(subset=["Close", "High", "Low"])
    except Exception:
        return pd.DataFrame()


# ---------------------------------------------------------------------------
# 가격 다운로드
# ---------------------------------------------------------------------------

def _normalize_krx_ohlc(df) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy().rename(columns={
        "시가": "Open",
        "고가": "High",
        "저가": "Low",
        "종가": "Close",
        "거래량": "Volume",
    })
    if "Close" not in out.columns:
        return pd.DataFrame()
    for col in ("High", "Low"):
        if col not in out.columns:
            out[col] = out["Close"]
    if "Volume" not in out.columns:
        out["Volume"] = 0
    cols = ["Close", "High", "Low", "Volume"]
    out = out[cols].apply(pd.to_numeric, errors="coerce")
    out.index = pd.to_datetime(out.index, errors="coerce")
    out = out[~out.index.isna()].sort_index().ffill()
    return out.dropna(subset=["Close", "High", "Low"])


@st.cache_data(ttl=900, show_spinner=False)
def _fetch_pykrx_ohlc(ticker: str) -> pd.DataFrame:
    if not _PYKRX_AVAILABLE:
        return pd.DataFrame()
    ticker = normalize_money_flow_ticker(ticker)
    if not _is_krx_money_flow_ticker(ticker):
        return pd.DataFrame()
    code = ticker.split(".", 1)[0]
    start = (pd.Timestamp.now() - pd.DateOffset(years=1)).strftime("%Y%m%d")
    end = pd.Timestamp.now().strftime("%Y%m%d")
    getters = []
    if hasattr(krx_stock, "get_market_ohlcv_by_date"):
        getters.append(lambda: krx_stock.get_market_ohlcv_by_date(start, end, code))
    if hasattr(krx_stock, "get_etf_ohlcv_by_date"):
        getters.append(lambda: krx_stock.get_etf_ohlcv_by_date(start, end, code))
    for getter in getters:
        try:
            out = _normalize_krx_ohlc(getter())
            if not out.empty:
                return out
        except Exception:
            continue
    return pd.DataFrame()


@st.cache_data(ttl=900, show_spinner=False)
def download_money_flow_prices(tickers) -> pd.DataFrame:
    tickers = sorted({normalize_money_flow_ticker(t) for t in tickers if str(t).strip()})
    if not tickers:
        return pd.DataFrame()
    yf_tickers = [
        t for t in tickers
        if not _is_krx_money_flow_ticker(t) and _money_flow_suffix(t) not in _UNRELIABLE_SUFFIXES
    ]
    if not yf_tickers:
        return pd.DataFrame()
    return yf.download(
        yf_tickers,
        period="1y",
        interval="1d",
        progress=False,
        group_by="ticker",
        threads=min(4, max(1, len(yf_tickers))),
        auto_adjust=False,
    )


def _extract_ohlc_from_yf(data: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """yfinance 멀티인덱스 DataFrame에서 단일 티커 OHLCV 추출."""
    if data is None or data.empty:
        return pd.DataFrame()
    if isinstance(data.columns, pd.MultiIndex):
        level0 = list(data.columns.get_level_values(0))
        level1 = list(data.columns.get_level_values(1))
        if ticker in level0:
            out = data[ticker].copy()
        elif ticker in level1:
            out = data.xs(ticker, axis=1, level=1).copy()
        else:
            return pd.DataFrame()
    else:
        out = data.copy()

    if not all(c in out.columns for c in ("Close", "High", "Low")):
        return pd.DataFrame()
    cols = ["Close", "High", "Low"] + (["Volume"] if "Volume" in out.columns else [])
    return out[cols].ffill().dropna(subset=["Close", "High", "Low"])


def get_money_flow_ohlc(data: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """yfinance 결과에서 OHLCV 추출. 실패 시 폴백 순서대로 시도.

    폴백 순서:
    1. yfinance (일괄 다운로드 결과)
    2. FinanceDataReader — .T(도쿄), .KS/.KQ(KRX 알파벳코드), fdr 전용 심볼
    3. Alpha Vantage    — 미국 상장 티커 한정 (AV_API_KEY 필요)
    """
    ticker = normalize_money_flow_ticker(ticker)
    suffix = _money_flow_suffix(ticker)

    if _is_krx_money_flow_ticker(ticker):
        out = _fetch_pykrx_ohlc(ticker)
        if out.empty and _FDR_AVAILABLE:
            out = _fetch_fdr_ohlc(ticker)
        return out

    if suffix == "T" and _FDR_AVAILABLE:
        out = _fetch_fdr_ohlc(ticker)
        if not out.empty:
            return out

    out = _extract_ohlc_from_yf(data, ticker)

    if out.empty and _FDR_AVAILABLE:
        # .T / KRX 알파벳코드 / fdr 전용 심볼에 한해 fdr 시도
        if suffix == "T" or not suffix:
            out = _fetch_fdr_ohlc(ticker)

    if out.empty and _AV_API_KEY:
        out = _fetch_alpha_vantage_ohlc(ticker)

    return out


# ---------------------------------------------------------------------------
# 수익률 및 거래량 계산
# ---------------------------------------------------------------------------

def get_return_by_days(close: pd.Series, days: int) -> float:
    """최근 `days` 거래일 수익률."""
    if close is None or len(close) < 2:
        return np.nan
    idx = -days if len(close) > days else 0
    old = float(close.iloc[idx])
    new = float(close.iloc[-1])
    return (new / old) - 1 if old > 0 else np.nan


def get_return_by_days_offset(close: pd.Series, days: int, offset: int = 0) -> float:
    """offset일 전을 기준 종점으로 삼아 `days` 거래일 수익률.

    예) get_return_by_days_offset(close, 63, offset=63)
        → 직전 3개월(3~6개월 전) 구간 수익률 — ret_3m과 기간이 겹치지 않음.

    accel = ret_3m - get_return_by_days_offset(close, 63, offset=63) 으로
    독립 구간 비교 기반의 진짜 가속도를 계산할 수 있음.
    """
    if close is None or len(close) < days + offset + 2:
        return np.nan
    new_pos = -(1 + offset)
    old_pos = -(1 + offset + days)
    old = float(close.iloc[old_pos])
    new = float(close.iloc[new_pos])
    return (new / old) - 1 if old > 0 else np.nan


def get_volume_growth(volume: pd.Series, recent_days: int = 20, base_days: int = 60) -> float:
    """최근 `recent_days` 평균 거래량 / 직전 `base_days` 평균 거래량 - 1."""
    if volume is None:
        return np.nan
    v = pd.Series(volume).dropna()
    if len(v) < recent_days + 5:
        return np.nan
    recent = float(v.tail(recent_days).mean())
    base_window = (
        v.iloc[-(recent_days + base_days):-recent_days]
        if len(v) >= recent_days + base_days
        else v.iloc[:-recent_days]
    )
    if base_window.empty:
        return np.nan
    base = float(base_window.mean())
    return (recent / base) - 1 if base > 0 else np.nan


# ---------------------------------------------------------------------------
# 점수·상태 계산
# ---------------------------------------------------------------------------

def _compute_flow_score(
    ret_1m: float,
    ret_3m: float,
    ret_6m: float,
    accel: float,
    volume_growth: float,
    price_level=None,
) -> float:
    """돈흐름 점수 계산.

    가중치 (합계 = 100):
        1개월  × 12  — 단기 모멘텀
        3개월  × 33  — 중기 모멘텀 (핵심)
        6개월  × 25  — 추세 지속성
        가속도 × 15  — 비겹치는 3m 구간 비교 (진짜 가속도)
        거래량 × 15  — 돈흐름 강도 (기존 5%에서 상향)

    오버히팅 패널티:
        price_level > 0.85 초과분 × 40 감산
        → 52주 신고가 부근에서 추격매수 억제 효과

    거래량 cap:
        volume_growth를 [-1.0, 1.5] 범위로 제한.
        단기 이상 급증(3배·10배 등)이 점수를 지배하는 현상 방지.
    """
    parts = _compute_flow_score_components(ret_1m, ret_3m, ret_6m, accel, volume_growth, price_level)
    return parts["점수_합계"]


def _compute_flow_score_components(
    ret_1m: float,
    ret_3m: float,
    ret_6m: float,
    accel: float,
    volume_growth: float,
    price_level=None,
) -> dict:
    """돈흐름 점수 구성요소를 개별 컬럼으로 남긴다."""
    overbought = max(0.0, (price_level - 0.85) * 40) if finite_num(price_level) else 0.0
    vol_capped = min(max(volume_growth, -1.0), 1.5) if finite_num(volume_growth) else 0.0
    parts = {
        "점수_1개월": (ret_1m if finite_num(ret_1m) else 0.0) * 12,
        "점수_3개월": (ret_3m if finite_num(ret_3m) else 0.0) * 33,
        "점수_6개월": (ret_6m if finite_num(ret_6m) else 0.0) * 25,
        "점수_가속도": (accel if finite_num(accel) else 0.0) * 15,
        "점수_거래량": vol_capped * 15,
        "점수_과열패널티": -overbought,
    }
    parts["점수_합계"] = sum(parts.values())
    return parts


def _compute_swing_score(
    ret_2w: float,
    ret_1m: float,
    swing_accel: float,
    volume_growth: float,
    price_level=None,
) -> float:
    """스윙 전용 점수 계산 (단기 민감도 특화).

    가중치 (합계 = 100):
        2주    × 25  — 최근 추세 방향
        1개월  × 35  — 단기 모멘텀 (핵심)
        단기가속도 × 25  — 최근 1m vs 직전 1m (방향 전환 포착)
        거래량 × 15  — 돈흐름 강도 확인

    오버히팅 패널티: price_level > 0.85 초과분 × 30 감산
    거래량 cap: volume_growth를 [-1.0, 1.5] 범위로 제한
    """
    overbought = max(0.0, (price_level - 0.85) * 30) if finite_num(price_level) else 0.0
    vol_capped = min(max(volume_growth, -1.0), 1.5) if finite_num(volume_growth) else 0.0
    return (
        (ret_2w        if finite_num(ret_2w)       else 0.0) * 25
        + (ret_1m      if finite_num(ret_1m)       else 0.0) * 35
        + (swing_accel if finite_num(swing_accel)  else 0.0) * 25
        + vol_capped * 15
        - overbought
    )


def classify_money_flow_state(
    ret_3m: float,
    ret_6m: float,
    accel: float,
    price_level: float | None = None,
) -> str:
    """돈흐름 상태 분류 (9단계).

    [고변동 계열 — abs(ret_3m)>8% AND abs(accel)>6%]
    과열경보 : 52주 고점 85% 초과 → 고점 추격 위험
    강세 가속: ret_3m>0 AND accel>0 (저점권 아니거나 6m 부진) → 상승·가속 중
    급락 경보: ret_3m<0 AND accel<0 → 하락하면서 가속 중 (나쁨)
    급반등   : 저점권(pl<0.40) + ret_3m>0 + ret_6m>-15% → 진짜 저점 반등
               (6m이 -15% 이하면 역배열 하락 중 단기 반등 → 강세 가속으로 분류)
    고변동   : 방향 혼재 (상승 중 급감속 등) → 관망 필요

    [일반 계열]
    신규 유입: ret_3m≥5% + accel≥3%
    주도 유지: ret_3m·6m 모두 ≥5% + accel 유지
    둔화 경고: ret_6m≥5% but accel≤-5%
    소외 지속: ret_3m·6m 모두 <0
    관찰     : 나머지
    """
    is_volatile = (
        finite_num(ret_3m) and finite_num(accel)
        and abs(ret_3m) > 0.08 and abs(accel) > 0.06
    )
    if is_volatile:
        pl = price_level if finite_num(price_level) else 0.5
        if pl > 0.85:
            return "과열경보"
        # 저점권 반등: 6m도 너무 부정적이지 않아야 진짜 반등
        # ret_6m < -0.15 이면 중기 하락추세 중 단기 되돌림(bear rally) → 강세 가속으로 분류
        if pl < 0.40 and ret_3m > 0:
            six_ok = (not finite_num(ret_6m)) or ret_6m > -0.15
            if six_ok:
                return "급반등"
        # 중간 구간(0.40~0.85) 또는 저점권이지만 6m이 -15% 이하: 방향성으로 세분화
        if ret_3m > 0 and accel > 0:
            return "강세 가속"
        if ret_3m < 0 and accel < 0:
            return "급락 경보"
        return "고변동"  # 상승 중 급감속 등 방향 혼재

    # 주도 유지 먼저 확인 (3m + 6m 모두 강함 = 확립된 상승 추세)
    if (finite_num(ret_3m) and finite_num(ret_6m)
            and ret_3m >= 0.05 and ret_6m >= 0.05
            and (not finite_num(accel) or accel >= -0.03)):
        return "주도 유지"
    # 신규 유입: 3m은 강하나 6m 미확인 또는 accel이 강한 초기 유입 신호
    if finite_num(ret_3m) and finite_num(accel) and ret_3m >= 0.05 and accel >= 0.03:
        return "신규 유입"
    if finite_num(ret_6m) and finite_num(accel) and ret_6m >= 0.05 and accel <= -0.05:
        return "둔화 경고"
    if finite_num(ret_3m) and finite_num(ret_6m) and ret_3m < 0 and ret_6m < 0:
        return "소외 지속"
    return "관찰"


def _compute_ticker_metrics(px: pd.DataFrame) -> dict:
    """단일 티커 OHLCV → 공통 메트릭 딕셔너리.

    calculate_money_flow_df / calculate_image_theme_flow_df 의
    중복 계산 로직을 여기서 통합 관리.
    """
    close       = px["Close"]
    cur         = float(close.iloc[-1])
    high_52w    = float(px["High"].max())
    low_52w     = float(px["Low"].min())
    period_ret  = get_return_by_days(close, len(close) - 1)
    ret_2w      = get_return_by_days(close, 10)
    ret_1m      = get_return_by_days(close, 21)
    ret_3m      = get_return_by_days(close, 63)
    ret_6m      = get_return_by_days(close, 126)

    # 중기 가속도: 최근 3개월 vs 직전 3개월 (비겹치는 독립 구간)
    ret_prev_3m = get_return_by_days_offset(close, 63, offset=63)
    accel = (ret_3m - ret_prev_3m) if finite_num(ret_3m) and finite_num(ret_prev_3m) else np.nan

    # 단기 가속도: 최근 1개월 vs 직전 1개월 (스윙용 방향 전환 포착)
    ret_prev_1m  = get_return_by_days_offset(close, 21, offset=21)
    swing_accel  = (ret_1m - ret_prev_1m) if finite_num(ret_1m) and finite_num(ret_prev_1m) else np.nan

    volume_growth = get_volume_growth(px["Volume"]) if "Volume" in px.columns else np.nan
    price_level   = (cur - low_52w) / (high_52w - low_52w) if high_52w > low_52w else np.nan
    flow_parts    = _compute_flow_score_components(ret_1m, ret_3m, ret_6m, accel, volume_growth, price_level)
    flow_score    = flow_parts["점수_합계"]
    swing_score   = _compute_swing_score(ret_2w, ret_1m, swing_accel, volume_growth, price_level)

    return {
        "현재가":      cur,
        "가격수준":    price_level,
        "기간수익률":  period_ret,
        "2주수익률":   ret_2w,
        "1개월수익률": ret_1m,
        "3개월수익률": ret_3m,
        "6개월수익률": ret_6m,
        "가속도":      accel,
        "단기가속도":  swing_accel,
        "거래량증가":  volume_growth,
        "돈흐름점수":  flow_score,
        "스윙점수":    swing_score,
        **flow_parts,
        "상태":        classify_money_flow_state(ret_3m, ret_6m, accel, price_level),
        "52주 최고가": high_52w,
        "52주 최저가": low_52w,
    }


# ---------------------------------------------------------------------------
# 메인 계산 함수
# ---------------------------------------------------------------------------

@st.cache_data(ttl=900, show_spinner=False)
def calculate_money_flow_df() -> pd.DataFrame:
    """MONEY_FLOW_UNIVERSE 전체 돈흐름 점수 계산 및 랭킹 반환."""
    universe = [
        dict(item, ticker=normalize_money_flow_ticker(item["ticker"]))
        for item in build_money_flow_universe_with_naver_rankings()
    ]
    data = download_money_flow_prices(tuple(item["ticker"] for item in universe))

    rows = []
    for item in universe:
        px = get_money_flow_ohlc(data, item["ticker"])
        if px.empty or len(px) < 20:
            continue
        metrics = _compute_ticker_metrics(px)
        rank_bonus = float(item.get("랭킹보조점수", 0.0) or 0.0)
        if rank_bonus:
            metrics["돈흐름점수"] = float(metrics.get("돈흐름점수", 0.0)) + rank_bonus
        metrics["점수_랭킹보조"] = rank_bonus
        rows.append({
            "구분":     item["구분"],
            "섹터":     item["섹터"],
            "Ticker":   item["ticker"],
            "ETF 이름": item["name"],
            "네이버랭킹": item.get("네이버랭킹", ""),
            **metrics,
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["히트맵크기"] = (df["3개월수익률"].abs().fillna(0) * 100).clip(lower=1)
    return df.sort_values("돈흐름점수", ascending=False)


@st.cache_data(ttl=900, show_spinner=False)
def calculate_image_theme_flow_df(theme: str) -> pd.DataFrame:
    """IMAGE_THEME_GROUPS 개별 종목 돈흐름 점수 계산."""
    selected = str(theme or "").strip()
    universe = [
        dict(item, ticker=normalize_money_flow_ticker(item["ticker"]))
        for item in IMAGE_THEME_UNIVERSE
        if not selected or item["테마"] == selected
    ]
    data = download_money_flow_prices(tuple(item["ticker"] for item in universe))

    _empty: dict = {
        "현재가": np.nan, "가격수준": np.nan, "기간수익률": np.nan,
        "2주수익률": np.nan, "1개월수익률": np.nan, "3개월수익률": np.nan, "6개월수익률": np.nan,
        "가속도": np.nan, "단기가속도": np.nan, "거래량증가": np.nan,
        "돈흐름점수": np.nan, "스윙점수": np.nan,
        "점수_1개월": np.nan, "점수_3개월": np.nan, "점수_6개월": np.nan,
        "점수_가속도": np.nan, "점수_거래량": np.nan, "점수_과열패널티": np.nan,
        "점수_합계": np.nan,
        "상태": "가격부족", "52주 최고가": np.nan, "52주 최저가": np.nan,
    }

    rows = []
    for item in universe:
        px = get_money_flow_ohlc(data, item["ticker"])
        metrics = _compute_ticker_metrics(px) if (not px.empty and len(px) >= 20) else _empty.copy()
        rows.append({
            "테마":     item["테마"],
            "하위테마": item["하위테마"],
            "종목명":   item["name"],
            "Ticker":   item["ticker"],
            **metrics,
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["히트맵크기"] = (df["3개월수익률"].abs().fillna(0) * 100).clip(lower=1)
    return df.sort_values(["하위테마", "돈흐름점수"], ascending=[True, False], na_position="last")


def calculate_image_theme_group_df(theme_flow_df: pd.DataFrame) -> pd.DataFrame:
    """하위테마 단위로 집계한 돈흐름 요약 반환."""
    if theme_flow_df is None or theme_flow_df.empty:
        return pd.DataFrame()
    valid = theme_flow_df.dropna(subset=["돈흐름점수"]).copy()
    if valid.empty:
        return pd.DataFrame()

    rows = []
    for (theme, subtheme), group in valid.groupby(["테마", "하위테마"], sort=False):
        leader        = group.sort_values("돈흐름점수", ascending=False).iloc[0]
        ret_2w        = group["2주수익률"].mean() if "2주수익률" in group.columns else np.nan
        ret_1m        = group["1개월수익률"].mean()
        ret_3m        = group["3개월수익률"].mean()
        ret_6m        = group["6개월수익률"].mean()
        accel         = group["가속도"].mean()
        short_accel   = group["단기가속도"].mean() if "단기가속도" in group.columns else np.nan
        volume_growth = group["거래량증가"].mean() if "거래량증가" in group.columns else np.nan
        flow_score    = group["돈흐름점수"].mean()
        price_level   = group["가격수준"].mean()
        up_ratio_2w   = group["2주수익률"].gt(0).mean() if "2주수익률" in group.columns else np.nan
        up_ratio_1m   = group["1개월수익률"].gt(0).mean()
        up_ratio      = group["3개월수익률"].gt(0).mean()
        score_abs     = group["돈흐름점수"].abs().dropna()
        concentration = (
            float(score_abs.max() / score_abs.sum())
            if not score_abs.empty and float(score_abs.sum()) > 0
            else np.nan
        )
        rows.append({
            "테마":       theme,
            "하위테마":   subtheme,
            "종목수":     int(len(group)),
            "대표주":     f"{leader['종목명']} ({leader['Ticker']})",
            "2주수익률":   ret_2w,
            "1개월수익률": ret_1m,
            "3개월수익률": ret_3m,
            "6개월수익률": ret_6m,
            "가속도":     accel,
            "단기가속도":  short_accel,
            "2주상승비율": up_ratio_2w,
            "1개월상승비율": up_ratio_1m,
            "상승종목비율": up_ratio,
            "거래량증가": volume_growth,
            "상위종목쏠림": concentration,
            "가격수준":   price_level,
            "돈흐름점수": flow_score,
            "점수_1개월": group["점수_1개월"].mean() if "점수_1개월" in group.columns else np.nan,
            "점수_3개월": group["점수_3개월"].mean() if "점수_3개월" in group.columns else np.nan,
            "점수_6개월": group["점수_6개월"].mean() if "점수_6개월" in group.columns else np.nan,
            "점수_가속도": group["점수_가속도"].mean() if "점수_가속도" in group.columns else np.nan,
            "점수_거래량": group["점수_거래량"].mean() if "점수_거래량" in group.columns else np.nan,
            "점수_과열패널티": group["점수_과열패널티"].mean() if "점수_과열패널티" in group.columns else np.nan,
            "상태":       classify_money_flow_state(ret_3m, ret_6m, accel, price_level),
            "구성종목":   ", ".join(group["종목명"].drop_duplicates().astype(str).tolist()),
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["히트맵크기"] = (df["3개월수익률"].abs().fillna(0) * 100).clip(lower=1)
    return df.sort_values("돈흐름점수", ascending=False)


def calculate_image_theme_rotation_df(theme_flow_df: pd.DataFrame) -> pd.DataFrame:
    """테마 단위 로테이션 점수 계산.

    테마 점수 구성:
        2주·1개월 확인 + 3개월 주도력 + 가속도 + 상승 확산 + 거래량 + 네이버 테마 보조
        - 상위 종목 쏠림/과열/하락 지속 패널티
    """
    if theme_flow_df is None or theme_flow_df.empty:
        return pd.DataFrame()
    all_rows = theme_flow_df.copy()
    valid    = all_rows.dropna(subset=["돈흐름점수"]).copy()
    if valid.empty:
        return pd.DataFrame()

    try:
        naver_theme_snapshot = fetch_naver_theme_context_snapshot()
    except Exception:
        naver_theme_snapshot = {}

    rows = []
    for theme, group in valid.groupby("테마", sort=False):
        total_count   = int((all_rows["테마"] == theme).sum())
        leader        = group.sort_values("돈흐름점수", ascending=False).iloc[0]
        weak          = group.sort_values("돈흐름점수", ascending=True).iloc[0]
        ret_2w        = group["2주수익률"].mean() if "2주수익률" in group.columns else np.nan
        ret_1m        = group["1개월수익률"].mean()
        ret_3m        = group["3개월수익률"].mean()
        ret_6m        = group["6개월수익률"].mean()
        accel         = group["가속도"].mean()
        short_accel   = group["단기가속도"].mean() if "단기가속도" in group.columns else np.nan
        volume_growth = group["거래량증가"].mean() if "거래량증가" in group.columns else np.nan
        price_level   = group["가격수준"].mean()
        up_ratio_2w   = group["2주수익률"].gt(0).mean() if "2주수익률" in group.columns else np.nan
        up_ratio_1m   = group["1개월수익률"].gt(0).mean()
        up_ratio_3m   = group["3개월수익률"].gt(0).mean()
        up_ratio_6m   = group["6개월수익률"].gt(0).mean()
        score_abs     = group["돈흐름점수"].abs().dropna()
        concentration = (
            float(score_abs.max() / score_abs.sum())
            if not score_abs.empty and float(score_abs.sum()) > 0
            else np.nan
        )

        breadth_mix = (
            (up_ratio_2w if finite_num(up_ratio_2w) else 0.5) * 0.35
            + (up_ratio_1m if finite_num(up_ratio_1m) else 0.5) * 0.35
            + (up_ratio_3m if finite_num(up_ratio_3m) else 0.5) * 0.30
        )
        # volume_growth cap [-1.0, 1.5]: 단기 이상급증이 테마 순위를 왜곡하지 않도록
        vol_capped_theme      = min(max(volume_growth, -1.0), 1.5) if finite_num(volume_growth) else 0.0
        naver_meta            = naver_theme_snapshot.get(theme, {}) if isinstance(naver_theme_snapshot, dict) else {}
        score_naver           = float(naver_meta.get("점수_네이버테마", 0.0) or 0.0)
        volume_bonus          = vol_capped_theme * 7
        concentration_penalty = (concentration if finite_num(concentration) else 0.0) * 8
        overbought_penalty    = max(0.0, (price_level - 0.86) * 24) if finite_num(price_level) else 0.0
        down_1m               = abs(min(ret_1m if finite_num(ret_1m) else 0.0, 0.0))
        down_2w               = abs(min(ret_2w if finite_num(ret_2w) else 0.0, 0.0))
        pullback_penalty      = 0.0
        if down_1m > 0 and down_2w > 0:
            pullback_penalty = min(8.0, 2.0 + down_1m * 30 + down_2w * 40)
        score_2w              = (ret_2w if finite_num(ret_2w) else 0.0) * 28
        score_1m              = (ret_1m if finite_num(ret_1m) else 0.0) * 26
        score_3m              = (ret_3m if finite_num(ret_3m) else 0.0) * 20
        score_6m              = (ret_6m if finite_num(ret_6m) else 0.0) * 8
        score_accel           = (accel if finite_num(accel) else 0.0) * 16
        score_short_accel     = (short_accel if finite_num(short_accel) else 0.0) * 14
        score_breadth         = (breadth_mix - 0.5) * 24
        score_volume          = volume_bonus
        score_concentration   = -concentration_penalty
        score_overbought      = -overbought_penalty
        score_downtrend       = -pullback_penalty

        theme_score = (
            score_2w
            + score_1m
            + score_3m
            + score_6m
            + score_accel
            + score_short_accel
            + score_breadth
            + score_volume
            + score_naver
            + score_concentration
            + score_overbought
            + score_downtrend
        )

        if (ret_1m if finite_num(ret_1m) else 0.0) <= -0.02 and (ret_2w if finite_num(ret_2w) else 0.0) < 0:
            theme_signal = "하락중 관망"
        elif finite_num(price_level) and price_level >= 0.90 and (ret_3m if finite_num(ret_3m) else 0.0) >= 0.10:
            theme_signal = "강하지만 과열"
        elif theme_score >= 10 and (ret_1m if finite_num(ret_1m) else 0.0) >= -0.005 and (ret_2w if finite_num(ret_2w) else 0.0) >= 0 and breadth_mix >= 0.52:
            theme_signal = "진입검토"
        elif theme_score >= 6 and (short_accel if finite_num(short_accel) else 0.0) >= 0 and (ret_1m if finite_num(ret_1m) else 0.0) >= -0.02 and breadth_mix >= 0.45:
            theme_signal = "부상감시"
        elif (ret_3m if finite_num(ret_3m) else 0.0) >= 0.08 and (ret_1m if finite_num(ret_1m) else 0.0) < 0:
            theme_signal = "주도 후 조정"
        else:
            theme_signal = "관망"

        rows.append({
            "테마":          theme,
            "종목수":        total_count,
            "계산종목수":    int(len(group)),
            "대표주":        f"{leader['종목명']} ({leader['Ticker']})",
            "약세주":        f"{weak['종목명']} ({weak['Ticker']})",
            "2주수익률":     ret_2w,
            "1개월수익률":   ret_1m,
            "3개월수익률":   ret_3m,
            "6개월수익률":   ret_6m,
            "가속도":        accel,
            "단기가속도":    short_accel,
            "상승종목비율":  up_ratio_3m,
            "2주상승비율":   up_ratio_2w,
            "1개월상승비율": up_ratio_1m,
            "6개월상승비율": up_ratio_6m,
            "거래량증가":    volume_growth,
            "상위종목쏠림":  concentration,
            "가격수준":      price_level,
            "테마돈흐름점수": theme_score,
            "테마판정":      theme_signal,
            "네이버테마근거": naver_meta.get("네이버테마근거", ""),
            "네이버테마상승비율": naver_meta.get("네이버테마상승비율", np.nan),
            "점수_2주":       score_2w,
            "점수_1개월":     score_1m,
            "점수_3개월":     score_3m,
            "점수_6개월":     score_6m,
            "점수_가속도":    score_accel,
            "점수_단기가속도": score_short_accel,
            "점수_상승비율":  score_breadth,
            "점수_거래량":    score_volume,
            "점수_네이버테마": score_naver,
            "점수_쏠림패널티": score_concentration,
            "점수_과열패널티": score_overbought,
            "점수_하락패널티": score_downtrend,
            "상태":          classify_money_flow_state(ret_3m, ret_6m, accel, price_level),
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["히트맵크기"] = (df["3개월수익률"].abs().fillna(0) * 100).clip(lower=1)
    return df.sort_values("테마돈흐름점수", ascending=False)


def calculate_sector_rotation_df(flow_df: pd.DataFrame) -> pd.DataFrame:
    """섹터 ETF 로테이션 사분면 계산 (RRG 스타일).

    RS(3M) = 섹터 3M수익률 - 벤치마크 3M수익률
    RS모멘텀 = 섹터 가속도 - 벤치마크 가속도
    사분면: 주도(RS≥0 & mom≥0), 약화(RS≥0 & mom<0),
            개선(RS<0 & mom≥0), 소외(RS<0 & mom<0)
    진입검토: 개선/주도 + 2주수익률≥+1% + 단기가속도≥0% + 상태≠과열경보
    """
    if flow_df is None or flow_df.empty:
        return pd.DataFrame()

    BENCH_MAP = {
        "한국 섹터": "069500.KS",
        "미국 섹터": "VOO",
        "글로벌":    "VOO",
    }

    rows = []
    for group, bench_ticker in BENCH_MAP.items():
        grp = flow_df[flow_df["구분"].astype(str) == group].copy()
        if grp.empty:
            continue
        bench_rows = grp[grp["Ticker"].astype(str) == bench_ticker]
        if bench_rows.empty:
            b_3m = 0.0
            b_accel = 0.0
        else:
            b = bench_rows.iloc[0]
            b_3m = float(b["3개월수익률"]) if finite_num(b.get("3개월수익률")) else 0.0
            b_accel = float(b["가속도"]) if finite_num(b.get("가속도")) else 0.0

        for _, r in grp.iterrows():
            if str(r.get("Ticker", "")) == bench_ticker:
                continue
            r3 = r.get("3개월수익률", np.nan)
            ac = r.get("가속도", np.nan)
            if not finite_num(r3) or not finite_num(ac):
                continue

            r2w = r.get("2주수익률", np.nan)
            r1m = r.get("1개월수익률", np.nan)
            swing_ac = r.get("단기가속도", np.nan)
            volume_growth = r.get("거래량증가", np.nan)
            price_level = r.get("가격수준", np.nan)
            rank_bonus = r.get("점수_랭킹보조", 0.0)
            flow_score = r.get("돈흐름점수", np.nan)
            state = str(r.get("상태", ""))

            rs_3m = float(r3) - b_3m
            rs_mom = float(ac) - b_accel

            # RS모멘텀 ±5% 이내는 노이즈로 간주 — 약화/개선 판정 제외
            # (예: UFO -3.6%, ICLN -1.6% → 실제 강세지만 약화 오표시 방지)
            _RS_MOM_BAND = 0.05
            if rs_3m >= 0 and rs_mom >= -_RS_MOM_BAND:
                quad = "주도"
            elif rs_3m >= 0 and rs_mom < -_RS_MOM_BAND:
                quad = "약화"
            elif rs_3m < 0 and rs_mom >= _RS_MOM_BAND:
                quad = "개선"
            else:
                quad = "소외"

            entry_ok = (
                quad in {"개선", "주도"}
                and finite_num(r2w) and float(r2w) >= 0.01
                and finite_num(swing_ac) and float(swing_ac) >= 0.0
                and state != "과열경보"
                # 주도 사분면은 RS가 실질적인 리더십(8% 이상)일 때만 진입검토
                # 개선 사분면은 RS < 0 → 역전 모멘텀이므로 임계값 불필요
                and (quad == "개선" or float(rs_3m) >= 0.08)
            )

            rows.append({
                "구분":       group,
                "섹터":       str(r.get("섹터", "")),
                "Ticker":     str(r.get("Ticker", "")),
                "사분면":     quad,
                "RS(3M)":     rs_3m,
                "RS모멘텀":   rs_mom,
                "3M수익률":   float(r3),
                "1개월수익률": float(r1m) if finite_num(r1m) else np.nan,
                "2주수익률":  float(r2w) if finite_num(r2w) else np.nan,
                "단기가속도": float(swing_ac) if finite_num(swing_ac) else np.nan,
                "거래량증가":  float(volume_growth) if finite_num(volume_growth) else np.nan,
                "가격수준":    float(price_level) if finite_num(price_level) else np.nan,
                "돈흐름점수":  float(flow_score) if finite_num(flow_score) else np.nan,
                "점수_랭킹보조": float(rank_bonus) if finite_num(rank_bonus) else 0.0,
                "네이버랭킹":  str(r.get("네이버랭킹", "")),
                "ETF 이름":    str(r.get("ETF 이름", "")),
                "상태":       state,
                "진입검토":   "✅ 진입검토" if entry_ok else "🔸 관망",
            })

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 섹터 로테이션 분석
# ---------------------------------------------------------------------------

def calculate_rotation_df(flow_df: pd.DataFrame) -> pd.DataFrame:
    """벤치마크 대비 상대강도(RS)와 RS 모멘텀으로 섹터 로테이션 사분면 분류.

    사분면 정의:
        주도(Leading)  : RS_3m >= 0 & RS모멘텀 >= 0  → 지금 돈 유입 중
        약화(Weakening): RS_3m >= 0 & RS모멘텀 <  0  → 강했지만 식는 중
        개선(Improving): RS_3m <  0 & RS모멘텀 >= 0  → 다음 주도 후보
        소외(Lagging)  : RS_3m <  0 & RS모멘텀 <  0  → 피해야 할 구간

    RS_3m    = 섹터_3m수익률 - 벤치마크_3m수익률
    RS모멘텀 = 섹터_가속도   - 벤치마크_가속도  (중기 가속도 기준)
    """
    if flow_df is None or flow_df.empty:
        return pd.DataFrame()

    # 그룹별 벤치마크 티커
    BENCHMARKS = {
        "한국 섹터": "069500.KS",  # KODEX 200
        "미국 섹터": "VOO",         # S&P500
        "글로벌":    "VOO",
    }

    rows = []
    for group, bench_ticker in BENCHMARKS.items():
        grp = flow_df[flow_df["구분"].astype(str) == group].copy()
        bench_rows = flow_df[flow_df["Ticker"].astype(str) == bench_ticker]
        if grp.empty or bench_rows.empty:
            continue

        b = bench_rows.iloc[0]
        b_3m    = float(b["3개월수익률"]) if finite_num(b.get("3개월수익률")) else 0.0
        b_accel = float(b["가속도"])      if finite_num(b.get("가속도"))      else 0.0

        for _, row in grp.iterrows():
            r3  = row.get("3개월수익률", np.nan)
            ac  = row.get("가속도",      np.nan)
            r1  = row.get("1개월수익률", np.nan)
            r2w = row.get("2주수익률",   np.nan)
            vg  = row.get("거래량증가",  np.nan)

            rs_3m  = float(r3) - b_3m    if finite_num(r3) else np.nan
            rs_mom = float(ac) - b_accel if finite_num(ac) else np.nan

            if finite_num(rs_3m) and finite_num(rs_mom):
                if   rs_3m >= 0 and rs_mom >= 0: quad = "주도"
                elif rs_3m >= 0 and rs_mom <  0: quad = "약화"
                elif rs_3m <  0 and rs_mom >= 0: quad = "개선"
                else:                             quad = "소외"
            else:
                quad = "-"

            rows.append({
                "구분":       group,
                "섹터":       row["섹터"],
                "Ticker":     row["Ticker"],
                "RS_3m":      rs_3m,
                "RS모멘텀":   rs_mom,
                "3개월수익률": r3,
                "1개월수익률": r1,
                "2주수익률":   r2w,
                "거래량증가":  vg,
                "로테이션":   quad,
                "상태":       row.get("상태", "-"),
            })

    return pd.DataFrame(rows) if rows else pd.DataFrame()


# ---------------------------------------------------------------------------
# 단일 섹터 상태 조회
# ---------------------------------------------------------------------------

@st.cache_data(ttl=900, show_spinner=False)
def get_sector_flow_state(sector_bench_ticker: str) -> str:
    """단일 섹터 벤치마크 티커의 돈흐름 상태를 반환."""
    if not sector_bench_ticker:
        return "-"
    data = download_money_flow_prices((sector_bench_ticker,))
    px   = get_money_flow_ohlc(data, sector_bench_ticker)
    if px.empty or len(px) < 20:
        return "-"
    return _compute_ticker_metrics(px)["상태"]
