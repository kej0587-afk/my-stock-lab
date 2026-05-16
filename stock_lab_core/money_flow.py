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
  - 제거: 0117V0.KS (TIGER 코리아AI전력기기TOP3플러스) — 알파벳 포함 KRX코드, yfinance 미지원
  - 제거: 0022T0.KS (SOL 국제금커버드콜액티브) — 동일 이유
  - 수정: 315930.KS 섹터 레이블 "인터넷/플랫폼" → "웹툰&게임"
  - 수정: RR.L (롤스로이스 런던) → RYCEY (뉴욕 ADR)

  [유니버스 추가]
  - 미국 섹터: LIT (리튬/EV), BOTZ (로봇/AI), FINX (핀테크)
  - 매크로: HYG (하이일드채권, 위험선호 선행지표)

  [선택적 기능]
  - Alpha Vantage 폴백: AV_API_KEY 환경변수 설정 시 yfinance 실패 티커에 한해 사용
    * 무료 티어 25 calls/day / KRX 티커는 AV 미지원으로 폴백 제외
"""

import os

import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf

try:
    import FinanceDataReader as fdr
    _FDR_AVAILABLE = True
except ImportError:
    _FDR_AVAILABLE = False


# ---------------------------------------------------------------------------
# 설정
# ---------------------------------------------------------------------------

# Alpha Vantage 선택적 폴백 (미국 상장 티커 한정)
# .env 또는 시스템 환경변수에 AV_API_KEY=<key> 설정 시 활성화
_AV_API_KEY: str = os.getenv("AV_API_KEY", "")

# yfinance 지원 불안정 해외 거래소 접미사
# .T(도쿄)는 fdr(TSE:) 폴백으로 처리 / .TW .VI .L 은 폴백 없음
_UNRELIABLE_SUFFIXES = {"T", "TW", "VI", "L"}


# ---------------------------------------------------------------------------
# 유틸리티
# ---------------------------------------------------------------------------

def finite_num(x) -> bool:
    """NaN / Inf / None 아닌 유효 숫자인지 확인."""
    return x is not None and not pd.isna(x) and np.isfinite(float(x))


# ---------------------------------------------------------------------------
# 유니버스 정의
# ---------------------------------------------------------------------------

MONEY_FLOW_UNIVERSE = [
    # ── 미국 섹터 ──────────────────────────────────────────────────────────
    {"구분": "미국 섹터", "섹터": "나스닥",          "ticker": "QQQ",  "name": "Invesco QQQ Trust"},
    {"구분": "미국 섹터", "섹터": "S&P500",          "ticker": "VOO",  "name": "Vanguard S&P 500 ETF"},
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
    {"구분": "한국 섹터", "섹터": "웹툰&게임",    "ticker": "315930.KS", "name": "KODEX Fn웹툰&게임"},  # 수정: 인터넷/플랫폼 → 웹툰&게임
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

    # ── 매크로 ─────────────────────────────────────────────────────────────
    {"구분": "매크로", "섹터": "금",           "ticker": "IAU",       "name": "iShares Gold Trust"},
    {"구분": "매크로", "섹터": "한국 금현물",  "ticker": "411060.KS", "name": "ACE KRX금현물"},
    {"구분": "매크로", "섹터": "미국 장기채",  "ticker": "TLT",       "name": "iShares 20+ Year Treasury Bond ETF"},
    {"구분": "매크로", "섹터": "비트코인",     "ticker": "IBIT",      "name": "iShares Bitcoin Trust"},       # 위험자산 선행지표
    {"구분": "매크로", "섹터": "미국 달러",    "ticker": "UUP",       "name": "Invesco DB US Dollar Index Bullish Fund"},
    {"구분": "매크로", "섹터": "미국 단기채",  "ticker": "SHV",       "name": "iShares Short Treasury Bond ETF"},  # 현금 대기 자금
    # [신규] 위험선호 선행지표 — 상승=리스크온, 하락=리스크오프
    {"구분": "매크로", "섹터": "하이일드채권", "ticker": "HYG",  "name": "iShares High Yield Corporate Bond ETF"},
    # [신규] 공포지수 — 점수 해석 주의: 상승=공포(리스크오프), 하강=안도(리스크온)
    {"구분": "매크로", "섹터": "공포지수(VIX)", "ticker": "^VIX", "name": "CBOE Volatility Index"},
]

IMAGE_THEME_GROUPS = [
    {
        "theme": "AI 에너지·전력",
        "groups": [
            ("원전/SMR", [
                ("두산에너빌리티", "034020.KS"), ("한전기술", "052690.KS"),
                ("현대건설", "000720.KS"), ("우리기술", "032820.KQ"),
            ]),
            ("태양광", [
                ("HD현대에너지솔루션", "322000.KS"), ("OCI홀딩스", "010060.KS"),
                ("한화솔루션", "009830.KS"),
            ]),
            ("풍력", [
                ("씨에스윈드", "112610.KS"), ("SK이터닉스", "475150.KS"),
                ("SK오션플랜트", "100090.KS"),
            ]),
            ("ESS", [
                ("삼성SDI", "006400.KS"), ("LG에너지솔루션", "373220.KS"),
                ("엘앤에프", "066970.KQ"), ("서진시스템", "178320.KQ"),
                ("한중엔시에스", "107640.KQ"),
            ]),
            ("SOFC", [
                ("두산퓨얼셀", "336260.KS"), ("코셈", "360350.KQ"),
                ("아모센스", "357580.KQ"),
            ]),
            ("슈퍼커패시터", [
                ("비나텍", "126340.KQ"), ("LS머트리얼즈", "417200.KQ"),
            ]),
            ("LNG", [
                ("한국가스공사", "036460.KS"), ("동성화인텍", "033500.KQ"),
                ("성광벤드", "014620.KQ"), ("태광", "023160.KQ"),
            ]),
            ("인프라건설", [
                ("현대건설", "000720.KS"), ("삼성E&A", "028050.KS"),
                ("대우건설", "047040.KS"), ("DL이앤씨", "375500.KS"),
            ]),
            ("가스터빈/HRSG", [
                ("두산에너빌리티", "034020.KS"), ("비에이치아이", "083650.KQ"),
            ]),
            ("인프라 냉각", [("SNT에너지", "100840.KS")]),
            ("서버 냉각", [("GST", "083450.KQ"), ("유니셈", "036200.KQ")]),
            ("전력관리", [("지투파워", "388050.KQ"), ("그리드위즈", "453450.KQ")]),
            ("변압기", [
                ("HD현대일렉트릭", "267260.KS"), ("LS ELECTRIC", "010120.KS"),
                ("효성중공업", "298040.KS"), ("산일전기", "062040.KS"),
            ]),
            ("케이블", [
                ("대한전선", "001440.KS"), ("일진전기", "103590.KS"),
                ("가온전선", "000500.KS"), ("LS에코에너지", "229640.KS"),
            ]),
            ("엔진", [
                ("HD현대중공업", "329180.KS"), ("한화엔진", "082740.KS"),
                ("HD현대마린엔진", "071970.KS"), ("STX엔진", "077970.KS"),
                ("지엔씨에너지", "119850.KQ"),
            ]),
        ],
    },
    {
        "theme": "AI 전력망·전력기기",
        "groups": [
            ("전력장비/변압기", [
                ("HD현대일렉트릭", "267260.KS"), ("LS ELECTRIC", "010120.KS"),
                ("효성중공업", "298040.KS"), ("산일전기", "062040.KS"),
                ("이튼", "ETN"), ("GE버노바", "GEV"),
            ]),
            ("케이블/전선", [
                ("대한전선", "001440.KS"), ("일진전기", "103590.KS"),
                ("가온전선", "000500.KS"), ("LS에코에너지", "229640.KS"),
            ]),
            ("전력관리/스마트그리드", [
                ("지투파워", "388050.KQ"), ("그리드위즈", "453450.KQ"),
                ("LS ELECTRIC", "010120.KS"), ("이튼", "ETN"),
            ]),
            ("데이터센터 전력/냉각", [
                ("버티브", "VRT"), ("이튼", "ETN"), ("GE버노바", "GEV"),
                ("HD현대일렉트릭", "267260.KS"), ("SNT에너지", "100840.KS"),
            ]),
            ("산업 자동화", [
                ("에머슨일렉트릭", "EMR"), ("허니웰", "HON"),
                ("록웰오토메이션", "ROK"), ("LS ELECTRIC", "010120.KS"),
            ]),
        ],
    },
    {
        "theme": "글로벌 원전·SMR",
        "groups": [
            ("전력 유틸리티", [("컨스텔레이션에너지", "CEG"), ("비스트라", "VST")]),
            ("SMR 개발사", [
                ("뉴스케일파워", "SMR"), ("오클로", "OKLO"),
                ("롤스로이스홀딩스", "RYCEY"),  # 수정: RR.L(런던 상장) → RYCEY(뉴욕 ADR)
            ]),
            ("원전 공급망", [("BWX테크놀로지스", "BWXT"), ("카메코", "CCJ"), ("두산에너빌리티", "034020.KS")]),
            ("우라늄/연료", [("카메코", "CCJ"), ("센트러스에너지", "LEU")]),
        ],
    },
    {
        "theme": "빅테크·AI 인프라",
        "groups": [
            ("클라우드 2대장", [("마이크로소프트", "MSFT"), ("아마존", "AMZN")]),
            ("플랫폼 AI", [("알파벳", "GOOGL"), ("메타", "META")]),
            ("소비자 생태계", [("애플", "AAPL"), ("넷플릭스", "NFLX")]),
            ("엔터프라이즈 클라우드", [("오라클", "ORCL"), ("IBM", "IBM")]),
            ("서버/OEM", [("델", "DELL"), ("HPE", "HPE"), ("슈퍼마이크로", "SMCI")]),
            ("네트워크", [("시스코", "CSCO"), ("아리스타", "ANET")]),
            ("AI 반도체 수요처", [("엔비디아", "NVDA"), ("AMD", "AMD"), ("브로드컴", "AVGO")]),
            ("AI 데이터/모빌리티", [("팔란티어", "PLTR"), ("우버", "UBER"), ("모바일아이", "MBLY"), ("테슬라", "TSLA")]),
            ("전력/냉각", [("GE버노바", "GEV"), ("버티브", "VRT"), ("이튼", "ETN")]),
        ],
    },
    {
        "theme": "나스닥 AI 반도체",
        "groups": [
            ("GPU/AI 가속기", [("엔비디아", "NVDA"), ("AMD", "AMD")]),
            ("ASIC/맞춤칩", [("브로드컴", "AVGO"), ("마벨", "MRVL")]),
            ("파운드리/장비", [("TSMC", "TSM"), ("ASML", "ASML")]),
            ("메모리/CPU", [("마이크론", "MU"), ("인텔", "INTC")]),
            ("서버/OEM", [("슈퍼마이크로", "SMCI"), ("델", "DELL"), ("HPE", "HPE")]),
            ("네트워크", [("아리스타", "ANET"), ("시스코", "CSCO")]),
            ("인터커넥트", [("아스테라랩스", "ALAB"), ("크레도테크", "CRDO")]),
            ("AI 플랫폼", [("마이크로소프트", "MSFT"), ("애플", "AAPL")]),
            ("데이터센터 냉각", [("버티브", "VRT")]),
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
    {
        "theme": "우주항공·방산",
        "groups": [
            ("한국 항공엔진", [("한화에어로스페이스", "012450.KS"), ("한국항공우주", "047810.KS")]),
            ("한국 유도무기", [("LIG넥스원", "079550.KS"), ("한화에어로스페이스", "012450.KS"), ("한화시스템", "272210.KS")]),
            ("한국 레이더/전자전", [("한화시스템", "272210.KS"), ("빅텍", "065450.KQ"), ("휴니드", "005870.KS")]),
            ("한국 전투기/항공기", [("한국항공우주", "047810.KS"), ("대한항공", "003490.KS"), ("켄코아에어로스페이스", "274090.KQ")]),
            ("한국 위성/통신", [("인텔리안테크", "189300.KQ"), ("AP위성", "211270.KQ"), ("제노코", "361390.KQ"), ("쎄트렉아이", "099320.KQ"), ("컨텍", "451760.KQ")]),
            ("한국 드론/UAM", [("퍼스텍", "010820.KS"), ("네온테크", "306620.KQ"), ("제노코", "361390.KQ")]),
            ("한국 함정/지상", [("HD현대중공업", "329180.KS"), ("한화오션", "042660.KS"), ("HJ중공업", "097230.KS"), ("현대로템", "064350.KS")]),
            ("한국 탄약/화약", [("풍산", "103140.KS"), ("한화", "000880.KS"), ("SNT다이내믹스", "003570.KS")]),
            ("미국 우주/위성", [("이리듐", "IRDM"), ("글로벌스타", "GSAT"), ("비아샛", "VSAT"), ("플래닛랩스", "PL"), ("블랙스카이", "BKSY"), ("로켓랩", "RKLB"), ("AST스페이스모바일", "ASTS")]),
            ("미국 방산 프라임", [("록히드마틴", "LMT"), ("RTX", "RTX"), ("노스롭그루먼", "NOC"), ("제너럴다이내믹스", "GD"), ("L3해리스", "LHX")]),
            ("미국 무인/드론", [("크라토스", "KTOS")]),
            ("미국 항공기", [("보잉", "BA")]),
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
]

IMAGE_THEME_UNIVERSE = [
    {"테마": tg["theme"], "하위테마": sub, "name": name, "ticker": ticker}
    for tg in IMAGE_THEME_GROUPS
    for sub, items in tg["groups"]
    for name, ticker in items
]


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

@st.cache_data(ttl=900, show_spinner=False)
def download_money_flow_prices(tickers) -> pd.DataFrame:
    tickers = sorted({normalize_money_flow_ticker(t) for t in tickers if str(t).strip()})
    if not tickers:
        return pd.DataFrame()
    return yf.download(
        tickers,
        period="1y",
        interval="1d",
        progress=False,
        group_by="ticker",
        threads=True,
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
    out = _extract_ohlc_from_yf(data, ticker)

    if out.empty and _FDR_AVAILABLE:
        suffix = ticker.split(".")[-1] if "." in ticker else ""
        # .T / KRX 알파벳코드 / fdr 전용 심볼에 한해 fdr 시도
        if suffix == "T" or suffix in ("KS", "KQ") or not suffix:
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
    """
    overbought = max(0.0, (price_level - 0.85) * 40) if finite_num(price_level) else 0.0
    return (
        (ret_1m        if finite_num(ret_1m)        else 0.0) * 12
        + (ret_3m      if finite_num(ret_3m)        else 0.0) * 33
        + (ret_6m      if finite_num(ret_6m)        else 0.0) * 25
        + (accel       if finite_num(accel)         else 0.0) * 15
        + (volume_growth if finite_num(volume_growth) else 0.0) * 15
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
        # ret_6m < -0.10 이면 중기 하락추세 중 단기 되돌림(bear rally) → 강세 가속으로 분류
        if pl < 0.40 and ret_3m > 0:
            six_ok = (not finite_num(ret_6m)) or ret_6m > -0.10
            if six_ok:
                return "급반등"
        # 중간 구간(0.40~0.85) 또는 저점권이지만 6m이 -15% 이하: 방향성으로 세분화
        if ret_3m > 0 and accel > 0:
            return "강세 가속"
        if ret_3m < 0 and accel < 0:
            return "급락 경보"
        return "고변동"  # 상승 중 급감속 등 방향 혼재

    if finite_num(ret_3m) and finite_num(accel) and ret_3m >= 0.05 and accel >= 0.03:
        return "신규 유입"
    if (finite_num(ret_3m) and finite_num(ret_6m)
            and ret_3m >= 0.05 and ret_6m >= 0.05
            and (not finite_num(accel) or accel >= -0.03)):
        return "주도 유지"
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
    ret_1m      = get_return_by_days(close, 21)
    ret_3m      = get_return_by_days(close, 63)
    ret_6m      = get_return_by_days(close, 126)

    # 가속도: 최근 3개월 vs 직전 3개월 (비겹치는 독립 구간)
    ret_prev_3m = get_return_by_days_offset(close, 63, offset=63)
    accel = (ret_3m - ret_prev_3m) if finite_num(ret_3m) and finite_num(ret_prev_3m) else np.nan

    volume_growth = get_volume_growth(px["Volume"]) if "Volume" in px.columns else np.nan
    price_level   = (cur - low_52w) / (high_52w - low_52w) if high_52w > low_52w else np.nan
    flow_score    = _compute_flow_score(ret_1m, ret_3m, ret_6m, accel, volume_growth, price_level)

    return {
        "현재가":      cur,
        "가격수준":    price_level,
        "기간수익률":  period_ret,
        "1개월수익률": ret_1m,
        "3개월수익률": ret_3m,
        "6개월수익률": ret_6m,
        "가속도":      accel,
        "거래량증가":  volume_growth,
        "돈흐름점수":  flow_score,
        "상태":        classify_money_flow_state(ret_3m, ret_6m, accel, price_level),
        "52주 최고가": high_52w,
        "52주 최저가": low_52w,
    }


# ---------------------------------------------------------------------------
# 메인 계산 함수
# ---------------------------------------------------------------------------

def calculate_money_flow_df() -> pd.DataFrame:
    """MONEY_FLOW_UNIVERSE 전체 돈흐름 점수 계산 및 랭킹 반환."""
    universe = [
        dict(item, ticker=normalize_money_flow_ticker(item["ticker"]))
        for item in MONEY_FLOW_UNIVERSE
    ]
    data = download_money_flow_prices(tuple(item["ticker"] for item in universe))

    rows = []
    for item in universe:
        px = get_money_flow_ohlc(data, item["ticker"])
        if px.empty or len(px) < 20:
            continue
        metrics = _compute_ticker_metrics(px)
        rows.append({
            "구분":     item["구분"],
            "섹터":     item["섹터"],
            "Ticker":   item["ticker"],
            "ETF 이름": item["name"],
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
        "1개월수익률": np.nan, "3개월수익률": np.nan, "6개월수익률": np.nan,
        "가속도": np.nan, "거래량증가": np.nan, "돈흐름점수": np.nan,
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
        ret_1m        = group["1개월수익률"].mean()
        ret_3m        = group["3개월수익률"].mean()
        ret_6m        = group["6개월수익률"].mean()
        accel         = group["가속도"].mean()
        volume_growth = group["거래량증가"].mean() if "거래량증가" in group.columns else np.nan
        flow_score    = group["돈흐름점수"].mean()
        price_level   = group["가격수준"].mean()
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
            "1개월수익률": ret_1m,
            "3개월수익률": ret_3m,
            "6개월수익률": ret_6m,
            "가속도":     accel,
            "상승종목비율": up_ratio,
            "거래량증가": volume_growth,
            "상위종목쏠림": concentration,
            "가격수준":   price_level,
            "돈흐름점수": flow_score,
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
        1개월 × 18 + 3개월 × 36 + 6개월 × 22 + 가속도 × 18
        + breadth_bonus       (상승 종목 비율 보정)
        + volume_bonus        (거래량 증가 보정)
        - concentration_penalty (상위 종목 쏠림 패널티)
        - overbought_penalty  (52주 고점 과열 패널티)
    """
    if theme_flow_df is None or theme_flow_df.empty:
        return pd.DataFrame()
    all_rows = theme_flow_df.copy()
    valid    = all_rows.dropna(subset=["돈흐름점수"]).copy()
    if valid.empty:
        return pd.DataFrame()

    rows = []
    for theme, group in valid.groupby("테마", sort=False):
        total_count   = int((all_rows["테마"] == theme).sum())
        leader        = group.sort_values("돈흐름점수", ascending=False).iloc[0]
        weak          = group.sort_values("돈흐름점수", ascending=True).iloc[0]
        ret_1m        = group["1개월수익률"].mean()
        ret_3m        = group["3개월수익률"].mean()
        ret_6m        = group["6개월수익률"].mean()
        accel         = group["가속도"].mean()
        volume_growth = group["거래량증가"].mean() if "거래량증가" in group.columns else np.nan
        price_level   = group["가격수준"].mean()
        up_ratio_1m   = group["1개월수익률"].gt(0).mean()
        up_ratio_3m   = group["3개월수익률"].gt(0).mean()
        up_ratio_6m   = group["6개월수익률"].gt(0).mean()
        score_abs     = group["돈흐름점수"].abs().dropna()
        concentration = (
            float(score_abs.max() / score_abs.sum())
            if not score_abs.empty and float(score_abs.sum()) > 0
            else np.nan
        )

        breadth_bonus         = (up_ratio_3m - 0.5) * 20
        volume_bonus          = (volume_growth if finite_num(volume_growth) else 0.0) * 6
        concentration_penalty = (concentration if finite_num(concentration) else 0.0) * 8
        overbought_penalty    = max(0.0, (price_level - 0.85) * 20) if finite_num(price_level) else 0.0

        theme_score = (
            (ret_1m if finite_num(ret_1m) else 0.0) * 18
            + (ret_3m if finite_num(ret_3m) else 0.0) * 36
            + (ret_6m if finite_num(ret_6m) else 0.0) * 22
            + (accel  if finite_num(accel)  else 0.0) * 18
            + breadth_bonus
            + volume_bonus
            - concentration_penalty
            - overbought_penalty
        )

        rows.append({
            "테마":          theme,
            "종목수":        total_count,
            "계산종목수":    int(len(group)),
            "대표주":        f"{leader['종목명']} ({leader['Ticker']})",
            "약세주":        f"{weak['종목명']} ({weak['Ticker']})",
            "1개월수익률":   ret_1m,
            "3개월수익률":   ret_3m,
            "6개월수익률":   ret_6m,
            "가속도":        accel,
            "상승종목비율":  up_ratio_3m,
            "1개월상승비율": up_ratio_1m,
            "6개월상승비율": up_ratio_6m,
            "거래량증가":    volume_growth,
            "상위종목쏠림":  concentration,
            "가격수준":      price_level,
            "테마돈흐름점수": theme_score,
            "상태":          classify_money_flow_state(ret_3m, ret_6m, accel, price_level),
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["히트맵크기"] = (df["3개월수익률"].abs().fillna(0) * 100).clip(lower=1)
    return df.sort_values("테마돈흐름점수", ascending=False)


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
    close       = px["Close"]
    high_52w    = float(px["High"].max())
    low_52w     = float(px["Low"].min())
    cur         = float(close.iloc[-1])
    price_level = (cur - low_52w) / (high_52w - low_52w) if high_52w > low_52w else None
    ret_3m      = get_return_by_days(close, 63)
    ret_6m      = get_return_by_days(close, 126)
    ret_prev_3m = get_return_by_days_offset(close, 63, offset=63)
    accel = (ret_3m - ret_prev_3m) if finite_num(ret_3m) and finite_num(ret_prev_3m) else np.nan
    return classify_money_flow_state(ret_3m, ret_6m, accel, price_level)
