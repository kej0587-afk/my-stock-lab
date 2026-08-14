"""Pure constants for Stock Lab — ETF lists, display names, classifier keywords.

이 모듈은 Python 내장 모듈 외 import가 없습니다.
stock_lab_core 어디서든 순환 import 없이 안전하게 import 가능합니다.
새 종목 표시명 추가 시 KNOWN_TICKER_DISPLAY_NAMES 만 수정하면 됩니다.
"""

# ─── US ETF 분류 ─────────────────────────────────────────────────────────────
KNOWN_US_SP_ETFS = {"SPY", "VOO", "IVV", "SPLG", "SPYM", "VTI"}
KNOWN_US_NASDAQ_ETFS = {"QQQ", "QQQM", "QLD", "TQQQ"}
KNOWN_US_OTHER_ETFS = {
    "DIA", "IWM", "SCHD", "JEPI", "JEPQ", "SMH", "SOXX", "SOXL", "DRAM", "RAM",
    "XLE", "XLF", "XLK", "XLC", "XLV", "XLI", "XLB", "XLY", "XLP", "XLU",
    "VNQ", "IBB", "ICLN", "SHLD", "PAVE", "ITA", "IGV", "URA", "IAU", "TLT",
    "IYW", "SSO", "UPRO", "SPXL", "SPXS", "SH", "SDS", "SQQQ", "QID", "PSQ",
    "TECL", "TECS", "SOXS", "LABU", "LABD", "TNA", "TZA", "FNGU", "FNGD",
    "NVDL", "NVDU", "NVDQ", "TSLL", "TSLQ",
    "HACK", "CIBR", "BUG",  # 사이버보안 ETF
}

# ─── KR ETF 심볼 ─────────────────────────────────────────────────────────────
KNOWN_KR_ETF_SYMBOLS = {
    "379810", "379800", "458730", "069500", "229200", "396500", "139260",
    "305540", "487240", "0117V0", "434730", "433500", "494670", "449450",
    "479850", "139250", "139270", "244580", "329200", "139220", "491010",
    "487230", "0167A0",
}

# ─── 재무 점수 면제 키워드 ────────────────────────────────────────────────────
FIN_SCORE_EXEMPT_ASSET_CLASS_KEYWORDS = (
    "etf", "etn", "fund", "lever", "inverse", "인버스", "레버리지"
)
KR_ETF_NAME_KEYWORDS = (
    "ETF", "ETN", "KODEX", "TIGER", "ACE", "SOL", "RISE", "KBSTAR",
    "HANARO", "KOSEF", "ARIRANG", "TIMEFOLIO", "히어로즈", "액티브", "레버리지", "인버스"
)

# ─── 종목 표시명 매핑 ─────────────────────────────────────────────────────────
# 새 종목 추가 시 이 딕셔너리만 수정하세요. 형식: "6자리코드": "표시명"
KNOWN_TICKER_DISPLAY_NAMES: dict[str, str] = {
    # 전력인프라
    "010120": "LS ELECTRIC",
    "267260": "HD현대일렉트릭",
    "298040": "효성중공업",
    "103590": "일진전기",
    "033100": "제룡전기",
    "001440": "대한전선",
    "006260": "LS",
    "083450": "GST",
    "062040": "산일전기",
    # 반도체
    "005930": "삼성전자",
    "000660": "SK하이닉스",
    "200710": "에이디테크놀러지",
    "042700": "한미반도체",
    "403870": "HPSP",
    "039030": "이오테크닉스",
    "058470": "리노공업",
    "095340": "ISC",
    "000990": "DB하이텍",
    "007660": "이수페타시스",
    # 원자력
    "034020": "두산에너빌리티",
    "052690": "한전기술",
    "051600": "한전KPS",
    # 조선
    "329180": "HD현대중공업",
    "009540": "HD한국조선해양",
    "010140": "삼성중공업",
    "042660": "한화오션",
    # 방산
    "012450": "한화에어로스페이스",
    "047810": "한국항공우주",
    "064350": "현대로템",
    "079550": "LIG넥스원",
    # K-뷰티
    "278470": "에이피알",
    "090430": "아모레퍼시픽",
    "161890": "한국콜마",
    "192820": "코스맥스",
    # 자동차
    "012330": "현대모비스",
    "307950": "현대오토에버",
    # 2차전지
    "373220": "LG에너지솔루션",
    "006400": "삼성SDI",
    "051910": "LG화학",
    "003670": "포스코퓨처엠",
    "247540": "에코프로비엠",
    "086520": "에코프로",
    "066970": "엘앤에프",
    # 영숫자 혼합 6자리 KR ETF 코드 (isdigit() 검사 우회)
    "0117V0": "TIGER 코리아AI전력기기TOP3플러스",
    "0022T0": "SOL 국제금커버드콜액티브",
    "0167A0": "SOL AI 반도체 Top2 플러스",
    # 미국 ETF
    "SOXL": "Direxion Daily Semiconductor Bull 3X Shares",
    "DRAM": "Roundhill Memory ETF",
    "RAM": "Roundhill T-REX 2X Long DRAM Daily Target ETF",
}
