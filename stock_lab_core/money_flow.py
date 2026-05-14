"""Money-flow universe and calculations for Stock Lab."""

import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf


def finite_num(x):
    return x is not None and not pd.isna(x) and np.isfinite(float(x))


FLOW_SCORE_WEIGHTS = {
    "ret_1m": 12,
    "ret_3m": 33,
    "ret_6m": 25,
    "accel": 15,
    "volume": 15,
}


def clamp_num(x, low, high):
    if not finite_num(x):
        return np.nan
    return min(max(float(x), low), high)


def classify_chase_risk(price_level, ret_1m=np.nan):
    if not finite_num(price_level):
        return "데이터부족"
    level = float(price_level)
    recent = float(ret_1m) if finite_num(ret_1m) else 0.0
    if level >= 0.92 and recent >= 0.10:
        return "추격주의"
    if level >= 0.85:
        return "고점권"
    if level <= 0.25:
        return "저점권"
    return "중립"


def calculate_flow_score(ret_1m, ret_3m, ret_6m, accel, volume_growth):
    volume_factor = clamp_num(volume_growth, -1.0, 2.0)
    return (
        (ret_1m if finite_num(ret_1m) else 0) * FLOW_SCORE_WEIGHTS["ret_1m"] +
        (ret_3m if finite_num(ret_3m) else 0) * FLOW_SCORE_WEIGHTS["ret_3m"] +
        (ret_6m if finite_num(ret_6m) else 0) * FLOW_SCORE_WEIGHTS["ret_6m"] +
        (accel if finite_num(accel) else 0) * FLOW_SCORE_WEIGHTS["accel"] +
        (volume_factor if finite_num(volume_factor) else 0) * FLOW_SCORE_WEIGHTS["volume"]
    )


MONEY_FLOW_UNIVERSE = [
    {"구분": "미국 섹터", "섹터": "나스닥", "ticker": "QQQ", "name": "Invesco QQQ Trust"},
    {"구분": "미국 섹터", "섹터": "S&P500", "ticker": "VOO", "name": "Vanguard S&P 500 ETF"},
    {"구분": "미국 섹터", "섹터": "반도체 VanEck", "ticker": "SMH", "name": "VanEck Semiconductor ETF"},
    {"구분": "미국 섹터", "섹터": "반도체 iShares", "ticker": "SOXX", "name": "iShares Semiconductor ETF"},
    {"구분": "미국 섹터", "섹터": "기술", "ticker": "XLK", "name": "Technology Select Sector SPDR"},
    {"구분": "미국 섹터", "섹터": "커뮤니케이션", "ticker": "XLC", "name": "Communication Services SPDR"},
    {"구분": "미국 섹터", "섹터": "금융", "ticker": "XLF", "name": "Financial Select Sector SPDR"},
    {"구분": "미국 섹터", "섹터": "헬스케어", "ticker": "XLV", "name": "Health Care Select Sector SPDR"},
    {"구분": "미국 섹터", "섹터": "에너지", "ticker": "XLE", "name": "Energy Select Sector SPDR"},
    {"구분": "미국 섹터", "섹터": "산업재", "ticker": "XLI", "name": "Industrial Select Sector SPDR"},
    {"구분": "미국 섹터", "섹터": "소재", "ticker": "XLB", "name": "Materials Select Sector SPDR"},
    {"구분": "미국 섹터", "섹터": "경기소비재", "ticker": "XLY", "name": "Consumer Discretionary SPDR"},
    {"구분": "미국 섹터", "섹터": "필수소비재", "ticker": "XLP", "name": "Consumer Staples SPDR"},
    {"구분": "미국 섹터", "섹터": "유틸리티", "ticker": "XLU", "name": "Utilities Select Sector SPDR"},
    {"구분": "미국 섹터", "섹터": "부동산", "ticker": "VNQ", "name": "Vanguard Real Estate ETF"},
    {"구분": "미국 섹터", "섹터": "바이오", "ticker": "IBB", "name": "iShares Biotechnology ETF"},
    {"구분": "미국 섹터", "섹터": "신재생", "ticker": "ICLN", "name": "iShares Global Clean Energy ETF"},
    {"구분": "미국 섹터", "섹터": "인프라", "ticker": "PAVE", "name": "Global X U.S. Infrastructure Development ETF"},
    {"구분": "미국 섹터", "섹터": "방산", "ticker": "SHLD", "name": "Global X Defense Tech ETF"},
    {"구분": "미국 섹터", "섹터": "항공방산", "ticker": "ITA", "name": "iShares U.S. Aerospace & Defense ETF"},
    {"구분": "미국 섹터", "섹터": "소프트웨어", "ticker": "IGV", "name": "iShares Expanded Tech-Software Sector ETF"},
    {"구분": "미국 섹터", "섹터": "사이버보안", "ticker": "CIBR", "name": "First Trust NASDAQ Cybersecurity ETF"},
    {"구분": "미국 섹터", "섹터": "2차전지/리튬", "ticker": "LIT", "name": "Global X Lithium & Battery Tech ETF"},
    {"구분": "미국 섹터", "섹터": "로봇/AI", "ticker": "BOTZ", "name": "Global X Robotics & Artificial Intelligence ETF"},
    {"구분": "미국 섹터", "섹터": "핀테크", "ticker": "FINX", "name": "Global X FinTech ETF"},
    {"구분": "미국 섹터", "섹터": "양자컴퓨팅", "ticker": "QTUM", "name": "Defiance Quantum ETF"},
    {"구분": "미국 섹터", "섹터": "주택건설", "ticker": "XHB", "name": "SPDR S&P Homebuilders ETF"},
    {"구분": "미국 섹터", "섹터": "원자재(구리)", "ticker": "COPX", "name": "Global X Copper Miners ETF"},

    # [추가] 한국 섹터 보완

    {"구분": "한국 섹터", "섹터": "코스피", "ticker": "069500.KS", "name": "KODEX 200"},
    {"구분": "한국 섹터", "섹터": "코스닥", "ticker": "229200.KS", "name": "KODEX 코스닥150"},
    {"구분": "한국 섹터", "섹터": "반도체", "ticker": "396500.KS", "name": "TIGER 반도체TOP10"},
    {"구분": "한국 섹터", "섹터": "IT/기술", "ticker": "139260.KS", "name": "TIGER 200 IT"},
    {"구분": "한국 섹터", "섹터": "2차전지", "ticker": "305540.KS", "name": "TIGER 2차전지테마"},
    {"구분": "한국 섹터", "섹터": "전력인프라", "ticker": "487240.KS", "name": "KODEX AI전력핵심설비"},
    {"구분": "한국 섹터", "섹터": "전력기기", "ticker": "0117V0.KS", "name": "TIGER 코리아AI전력기기TOP3플러스"},
    {"구분": "한국 섹터", "섹터": "원자력", "ticker": "434730.KS", "name": "HANARO 원자력iSelect"},
    {"구분": "한국 섹터", "섹터": "원자력TOP10", "ticker": "433500.KS", "name": "ACE 원자력TOP10"},
    {"구분": "한국 섹터", "섹터": "조선", "ticker": "494670.KS", "name": "TIGER 조선TOP10"},
    {"구분": "한국 섹터", "섹터": "방산", "ticker": "449450.KS", "name": "PLUS K방산"},
    {"구분": "한국 섹터", "섹터": "K-뷰티", "ticker": "479850.KS", "name": "HANARO K-뷰티"},
    {"구분": "한국 섹터", "섹터": "화장품", "ticker": "228790.KS", "name": "TIGER 화장품"}, # K-뷰티와 함께 묶어서 관찰
    {"구분": "한국 섹터", "섹터": "웹툰&드라마", "ticker": "395150.KS", "name": "KODEX 웹툰&드라마"},
    {"구분": "한국 섹터", "섹터": "게임", "ticker": "300950.KS", "name": "KODEX 게임산업"},
    {"구분": "한국 섹터", "섹터": "에너지", "ticker": "139250.KS", "name": "TIGER 200 에너지화학"},
    {"구분": "한국 섹터", "섹터": "금융", "ticker": "139270.KS", "name": "TIGER 200 금융"},
    {"구분": "한국 섹터", "섹터": "바이오", "ticker": "244580.KS", "name": "KODEX 바이오"},
    {"구분": "한국 섹터", "섹터": "부동산", "ticker": "329200.KS", "name": "TIGER 리츠부동산인프라"},
    {"구분": "한국 섹터", "섹터": "건설/유틸", "ticker": "139220.KS", "name": "TIGER 200 건설"},

    {"구분": "월배당 ETF", "섹터": "금리형", "ticker": "459580.KS", "name": "KODEX CD금리액티브(합성)"},
    {"구분": "월배당 ETF", "섹터": "국내 단기채", "ticker": "214980.KS", "name": "KODEX 단기채권PLUS"},
    {"구분": "월배당 ETF", "섹터": "미국 장기채", "ticker": "453850.KS", "name": "ACE 미국30년국채액티브(H)"},
    {"구분": "월배당 ETF", "섹터": "장기채 커버드콜", "ticker": "476550.KS", "name": "TIGER 미국30년국채커버드콜액티브(H)"},
    {"구분": "월배당 ETF", "섹터": "국내 리츠", "ticker": "329200.KS", "name": "TIGER 리츠부동산인프라"},
    {"구분": "월배당 ETF", "섹터": "국내 고배당", "ticker": "161510.KS", "name": "PLUS 고배당주"},
    {"구분": "월배당 ETF", "섹터": "은행 고배당", "ticker": "466940.KS", "name": "TIGER 은행고배당플러스TOP10"},
    {"구분": "월배당 ETF", "섹터": "미국 배당", "ticker": "458730.KS", "name": "TIGER 미국배당다우존스"},
    {"구분": "월배당 ETF", "섹터": "미국 배당 커버드콜", "ticker": "458760.KS", "name": "TIGER 미국배당다우존스타겟커버드콜2호"},
    {"구분": "월배당 ETF", "섹터": "나스닥100 커버드콜", "ticker": "486290.KS", "name": "TIGER 미국나스닥100타겟데일리커버드콜"},
    {"구분": "월배당 ETF", "섹터": "S&P500 커버드콜", "ticker": "482730.KS", "name": "TIGER 미국S&P500타겟데일리커버드콜"},
    {"구분": "월배당 ETF", "섹터": "KOSPI200 커버드콜", "ticker": "498400.KS", "name": "KODEX 200타겟위클리커버드콜"},
    {"구분": "월배당 ETF", "섹터": "미국 테크 커버드콜", "ticker": "474220.KS", "name": "TIGER 미국테크TOP10타겟커버드콜"},
    {"구분": "월배당 ETF", "섹터": "금 커버드콜", "ticker": "0022T0.KS", "name": "SOL 국제금커버드콜액티브"},

    {"구분": "국내상장 대표 ETF", "섹터": "KOSPI200 대형", "ticker": "102110.KS", "name": "TIGER 200"},
    {"구분": "국내상장 대표 ETF", "섹터": "미국 S&P500", "ticker": "360750.KS", "name": "TIGER 미국S&P500"},
    {"구분": "국내상장 대표 ETF", "섹터": "미국 나스닥100", "ticker": "133690.KS", "name": "TIGER 미국나스닥100"},
    {"구분": "국내상장 대표 ETF", "섹터": "인도 Nifty50", "ticker": "453870.KS", "name": "TIGER 인도니프티50"},
    {"구분": "국내상장 대표 ETF", "섹터": "일본 Nikkei225", "ticker": "241180.KS", "name": "TIGER 일본니케이225"},
    {"구분": "국내상장 대표 ETF", "섹터": "중국 CSI300", "ticker": "192090.KS", "name": "TIGER 차이나CSI300"},
    {"구분": "국내상장 대표 ETF", "섹터": "미국 반도체", "ticker": "381180.KS", "name": "TIGER 미국필라델피아반도체나스닥"},
    {"구분": "국내상장 대표 ETF", "섹터": "중국 전기차", "ticker": "371460.KS", "name": "TIGER 차이나전기차SOLACTIVE"},
    {"구분": "국내상장 대표 ETF", "섹터": "글로벌 AI", "ticker": "456600.KS", "name": "TIMEFOLIO 글로벌AI인공지능액티브"},
    {"구분": "국내상장 대표 ETF", "섹터": "헬스케어", "ticker": "143860.KS", "name": "TIGER 헬스케어"},
    {"구분": "국내상장 대표 ETF", "섹터": "종합채권", "ticker": "273130.KS", "name": "KODEX 종합채권(AA-이상)액티브"},
    {"구분": "국내상장 대표 ETF", "섹터": "머니마켓", "ticker": "488770.KS", "name": "KODEX 머니마켓액티브"},

    {"구분": "글로벌", "섹터": "미국 나스닥", "ticker": "QQQ", "name": "Invesco QQQ Trust"},
    {"구분": "글로벌", "섹터": "미국 S&P500", "ticker": "VOO", "name": "Vanguard S&P 500 ETF"},
    {"구분": "글로벌", "섹터": "일본", "ticker": "EWJ", "name": "iShares MSCI Japan ETF"},
    {"구분": "글로벌", "섹터": "캐나다", "ticker": "EWC", "name": "iShares MSCI Canada ETF"},
    {"구분": "글로벌", "섹터": "한국", "ticker": "EWY", "name": "iShares MSCI South Korea ETF"},
    {"구분": "글로벌", "섹터": "대만", "ticker": "EWT", "name": "iShares MSCI Taiwan ETF"},
    {"구분": "글로벌", "섹터": "홍콩", "ticker": "EWH", "name": "iShares MSCI Hong Kong ETF"},
    {"구분": "글로벌", "섹터": "중국", "ticker": "MCHI", "name": "iShares MSCI China ETF"},
    {"구분": "글로벌", "섹터": "인도", "ticker": "FLIN", "name": "Franklin FTSE India ETF"},
    {"구분": "글로벌", "섹터": "글로벌AI전력인프라", "ticker": "491010.KS", "name": "TIGER 글로벌AI전력인프라액티브"},
    {"구분": "글로벌", "섹터": "미국AI전력인프라", "ticker": "487230.KS", "name": "KODEX 미국AI전력핵심인프라"},
    {"구분": "글로벌", "섹터": "우라늄/원전", "ticker": "URA", "name": "Global X Uranium ETF"},
    {"구분": "글로벌", "섹터": "브라질", "ticker": "EWZ", "name": "iShares MSCI Brazil ETF"},
    {"구분": "글로벌", "섹터": "멕시코", "ticker": "EWW", "name": "iShares MSCI Mexico ETF"},
    {"구분": "글로벌", "섹터": "사우디", "ticker": "KSA", "name": "iShares MSCI Saudi Arabia ETF"},
    {"구분": "글로벌", "섹터": "베트남", "ticker": "VNM", "name": "VanEck Vietnam ETF"},

    {"구분": "매크로", "섹터": "금", "ticker": "IAU", "name": "iShares Gold Trust"},
    {"구분": "매크로", "섹터": "한국 금현물", "ticker": "411060.KS", "name": "ACE KRX금현물"},
    {"구분": "매크로", "섹터": "미국 장기채", "ticker": "TLT", "name": "iShares 20+ Year Treasury Bond ETF"},
    {"구분": "매크로", "섹터": "하이일드채권", "ticker": "HYG", "name": "iShares iBoxx High Yield Corporate Bond ETF"},
    {"구분": "매크로", "섹터": "비트코인", "ticker": "IBIT", "name": "iShares Bitcoin Trust"}, # 위험자산(Risk-on) 돈흐름 선행지표
    {"구분": "매크로", "섹터": "미국 달러", "ticker": "UUP", "name": "Invesco DB US Dollar Index Bullish Fund"},
    {"구분": "매크로", "섹터": "미국 단기채", "ticker": "SHV", "name": "iShares Short Treasury Bond ETF"}, # 현금 대기성 자금 흐름 파악용
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
            ("SMR 개발사", [("뉴스케일파워", "SMR"), ("오클로", "OKLO"), ("롤스로이스홀딩스", "RYCEY")]),
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
    {"테마": theme_group["theme"], "하위테마": subtheme, "name": name, "ticker": ticker}
    for theme_group in IMAGE_THEME_GROUPS
    for subtheme, items in theme_group["groups"]
    for name, ticker in items
]


def get_image_theme_names():
    return [group["theme"] for group in IMAGE_THEME_GROUPS]


def normalize_money_flow_ticker(ticker):
    t = str(ticker).strip().upper()
    if t.endswith(".KS") or t.endswith(".KQ"):
        code, suffix = t.split(".", 1)
        return f"{code.zfill(6)}.{suffix}"
    return t

@st.cache_data(ttl=900, show_spinner=False)
def download_money_flow_prices(tickers):
    tickers = sorted({normalize_money_flow_ticker(t) for t in tickers if str(t).strip()})
    if not tickers:
        return pd.DataFrame()
    data = yf.download(
        tickers,
        period="1y",
        interval="1d",
        progress=False,
        group_by="ticker",
        threads=True,
        auto_adjust=False,
    )
    return data

def get_money_flow_ohlc(data, ticker):
    ticker = normalize_money_flow_ticker(ticker)
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

    needed = [c for c in ["Close", "High", "Low"] if c in out.columns]
    if len(needed) < 3:
        return pd.DataFrame()

    cols = ["Close", "High", "Low"]
    if "Volume" in out.columns:
        cols.append("Volume")
    out = out[cols].ffill().dropna(subset=["Close", "High", "Low"])
    return out

def get_return_by_days(close, days):
    if close is None or len(close) < 2:
        return np.nan
    idx = -days if len(close) > days else 0
    old = float(close.iloc[idx])
    new = float(close.iloc[-1])
    if old <= 0:
        return np.nan
    return (new / old) - 1


def get_return_by_days_offset(close, days, offset=0):
    if close is None:
        return np.nan
    s = pd.Series(close).dropna()
    if len(s) < 2:
        return np.nan

    offset = max(int(offset or 0), 0)
    if len(s) <= offset + 1:
        return np.nan

    new_idx = -(1 + offset) if offset > 0 else -1
    old_idx = -(days + offset)
    if abs(old_idx) > len(s):
        return np.nan

    old = float(s.iloc[old_idx])
    new = float(s.iloc[new_idx])
    if old <= 0:
        return np.nan
    return (new / old) - 1


def get_volume_growth(volume, recent_days=20, base_days=60):
    if volume is None:
        return np.nan
    v = pd.Series(volume).dropna()
    if len(v) < recent_days + 5:
        return np.nan

    recent = float(v.tail(recent_days).mean())
    base_window = v.iloc[-(recent_days + base_days):-recent_days] if len(v) >= recent_days + base_days else v.iloc[:-recent_days]
    if base_window.empty:
        return np.nan
    base = float(base_window.mean())
    if base <= 0:
        return np.nan
    return (recent / base) - 1

def classify_money_flow_state(ret_3m, ret_6m, accel, relative_3m=np.nan):
    rel_3m = relative_3m if finite_num(relative_3m) else ret_3m
    if finite_num(ret_3m) and finite_num(accel) and finite_num(rel_3m) and rel_3m >= 0.03 and accel >= 0.03:
        return "신규 유입"
    if finite_num(ret_3m) and finite_num(ret_6m) and finite_num(rel_3m) and ret_3m >= 0.05 and ret_6m >= 0.05 and rel_3m >= -0.02 and (not finite_num(accel) or accel >= -0.03):
        return "주도 유지"
    if finite_num(ret_6m) and finite_num(accel) and ret_6m >= 0.05 and (accel <= -0.05 or (finite_num(rel_3m) and rel_3m <= -0.05)):
        return "둔화 경고"
    if finite_num(ret_3m) and finite_num(ret_6m) and finite_num(rel_3m) and ret_3m < 0 and ret_6m < 0 and rel_3m < 0:
        return "소외 지속"
    if finite_num(ret_3m) and finite_num(rel_3m) and ret_3m >= 0 and rel_3m <= -0.05:
        return "상대 약세"
    return "관찰"


def apply_relative_money_flow_state(df, group_col=None, score_col="돈흐름점수"):
    if df is None or df.empty or "3개월수익률" not in df.columns:
        return df
    out = df.copy()
    out["상대3개월수익률"] = np.nan

    if group_col and group_col in out.columns:
        groups = out.groupby(group_col, dropna=False).groups.values()
    else:
        groups = [out.index]

    for idxs in groups:
        idxs = list(idxs)
        valid = out.loc[idxs, "3개월수익률"].dropna()
        if valid.empty:
            continue
        baseline = float(valid.quantile(0.60))
        out.loc[idxs, "상대3개월수익률"] = out.loc[idxs, "3개월수익률"] - baseline

    out["상태"] = out.apply(
        lambda r: r["상태"] if r.get("상태") == "가격부족" else classify_money_flow_state(
            r.get("3개월수익률"),
            r.get("6개월수익률"),
            r.get("가속도"),
            r.get("상대3개월수익률"),
        ),
        axis=1,
    )

    if score_col in out.columns:
        sort_cols = [score_col]
        ascending = [False]
        if "유니버스순번" in out.columns:
            sort_cols.append("유니버스순번")
            ascending.append(True)
        return out.sort_values(sort_cols, ascending=ascending, na_position="last")
    return out

def calculate_money_flow_df():
    universe = [
        dict(item, ticker=normalize_money_flow_ticker(item["ticker"]), _order=i)
        for i, item in enumerate(MONEY_FLOW_UNIVERSE)
    ]
    tickers = [item["ticker"] for item in universe]
    data = download_money_flow_prices(tickers)

    rows = []
    for item in universe:
        px = get_money_flow_ohlc(data, item["ticker"])
        if px.empty or len(px) < 20:
            rows.append({
                "구분": item["구분"],
                "섹터": item["섹터"],
                "Ticker": item["ticker"],
                "ETF 이름": item["name"],
                "현재가": np.nan,
                "가격수준": np.nan,
                "기간수익률": np.nan,
                "1개월수익률": np.nan,
                "3개월수익률": np.nan,
                "이전3개월수익률": np.nan,
                "상대3개월수익률": np.nan,
                "6개월수익률": np.nan,
                "가속도": np.nan,
                "거래량증가": np.nan,
                "돈흐름점수": np.nan,
                "상태": "가격부족",
                "추격위험": "데이터부족",
                "52주 최고가": np.nan,
                "52주 최저가": np.nan,
                "유니버스순번": item["_order"],
            })
            continue

        close = px["Close"]
        cur = float(close.iloc[-1])
        high_52w = float(px["High"].max())
        low_52w = float(px["Low"].min())
        period_ret = get_return_by_days(close, len(close) - 1)
        ret_1m = get_return_by_days(close, 21)
        ret_3m = get_return_by_days(close, 63)
        ret_6m = get_return_by_days(close, 126)
        ret_prev_3m = get_return_by_days_offset(close, 63, offset=63)
        accel = ret_3m - ret_prev_3m if finite_num(ret_3m) and finite_num(ret_prev_3m) else np.nan
        volume_growth = get_volume_growth(px["Volume"]) if "Volume" in px.columns else np.nan
        price_level = (cur - low_52w) / (high_52w - low_52w) if high_52w > low_52w else np.nan
        flow_score = calculate_flow_score(ret_1m, ret_3m, ret_6m, accel, volume_growth)

        rows.append({
            "구분": item["구분"],
            "섹터": item["섹터"],
            "Ticker": item["ticker"],
            "ETF 이름": item["name"],
            "현재가": cur,
            "가격수준": price_level,
            "기간수익률": period_ret,
            "1개월수익률": ret_1m,
            "3개월수익률": ret_3m,
            "이전3개월수익률": ret_prev_3m,
            "상대3개월수익률": np.nan,
            "6개월수익률": ret_6m,
            "가속도": accel,
            "거래량증가": volume_growth,
            "돈흐름점수": flow_score,
            "상태": classify_money_flow_state(ret_3m, ret_6m, accel),
            "추격위험": classify_chase_risk(price_level, ret_1m),
            "52주 최고가": high_52w,
            "52주 최저가": low_52w,
            "유니버스순번": item["_order"],
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    df["히트맵크기"] = (df["3개월수익률"].abs().fillna(0) * 100).clip(lower=1)
    return apply_relative_money_flow_state(df, group_col="구분", score_col="돈흐름점수")


@st.cache_data(ttl=900, show_spinner=False)
def calculate_image_theme_flow_df(theme):
    selected_theme = str(theme or "").strip()
    universe = []
    for item in IMAGE_THEME_UNIVERSE:
        if selected_theme and item["테마"] != selected_theme:
            continue
        universe.append(dict(item, ticker=normalize_money_flow_ticker(item["ticker"])))

    tickers = [item["ticker"] for item in universe]
    data = download_money_flow_prices(tickers)

    rows = []
    for item in universe:
        px = get_money_flow_ohlc(data, item["ticker"])
        if px.empty or len(px) < 20:
            rows.append({
                "테마": item["테마"],
                "하위테마": item["하위테마"],
                "종목명": item["name"],
                "Ticker": item["ticker"],
                "현재가": np.nan,
                "가격수준": np.nan,
                "기간수익률": np.nan,
                "1개월수익률": np.nan,
                "3개월수익률": np.nan,
                "이전3개월수익률": np.nan,
                "상대3개월수익률": np.nan,
                "6개월수익률": np.nan,
                "가속도": np.nan,
                "거래량증가": np.nan,
                "돈흐름점수": np.nan,
                "상태": "가격부족",
                "추격위험": "데이터부족",
                "52주 최고가": np.nan,
                "52주 최저가": np.nan,
            })
            continue

        close = px["Close"]
        cur = float(close.iloc[-1])
        high_52w = float(px["High"].max())
        low_52w = float(px["Low"].min())
        period_ret = get_return_by_days(close, len(close) - 1)
        ret_1m = get_return_by_days(close, 21)
        ret_3m = get_return_by_days(close, 63)
        ret_6m = get_return_by_days(close, 126)
        ret_prev_3m = get_return_by_days_offset(close, 63, offset=63)
        accel = ret_3m - ret_prev_3m if finite_num(ret_3m) and finite_num(ret_prev_3m) else np.nan
        volume_growth = get_volume_growth(px["Volume"]) if "Volume" in px.columns else np.nan
        price_level = (cur - low_52w) / (high_52w - low_52w) if high_52w > low_52w else np.nan
        flow_score = calculate_flow_score(ret_1m, ret_3m, ret_6m, accel, volume_growth)

        rows.append({
            "테마": item["테마"],
            "하위테마": item["하위테마"],
            "종목명": item["name"],
            "Ticker": item["ticker"],
            "현재가": cur,
            "가격수준": price_level,
            "기간수익률": period_ret,
            "1개월수익률": ret_1m,
            "3개월수익률": ret_3m,
            "이전3개월수익률": ret_prev_3m,
            "상대3개월수익률": np.nan,
            "6개월수익률": ret_6m,
            "가속도": accel,
            "거래량증가": volume_growth,
            "돈흐름점수": flow_score,
            "상태": classify_money_flow_state(ret_3m, ret_6m, accel),
            "추격위험": classify_chase_risk(price_level, ret_1m),
            "52주 최고가": high_52w,
            "52주 최저가": low_52w,
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["히트맵크기"] = (df["3개월수익률"].abs().fillna(0) * 100).clip(lower=1)
    df = apply_relative_money_flow_state(df, group_col="테마", score_col="돈흐름점수")
    return df.sort_values(["하위테마", "돈흐름점수"], ascending=[True, False], na_position="last")


def calculate_image_theme_group_df(theme_flow_df):
    if theme_flow_df is None or theme_flow_df.empty:
        return pd.DataFrame()

    valid = theme_flow_df.dropna(subset=["돈흐름점수"]).copy()
    if valid.empty:
        return pd.DataFrame()

    rows = []
    for (theme, subtheme), group in valid.groupby(["테마", "하위테마"], sort=False):
        leader = group.sort_values("돈흐름점수", ascending=False).iloc[0]
        ret_1m = group["1개월수익률"].mean()
        ret_3m = group["3개월수익률"].mean()
        ret_prev_3m = group["이전3개월수익률"].mean() if "이전3개월수익률" in group.columns else np.nan
        ret_6m = group["6개월수익률"].mean()
        accel = group["가속도"].mean()
        volume_growth = group["거래량증가"].mean() if "거래량증가" in group.columns else np.nan
        flow_score = group["돈흐름점수"].mean()
        price_level = group["가격수준"].mean()
        up_ratio = group["3개월수익률"].gt(0).mean()
        score_abs = group["돈흐름점수"].abs().dropna()
        concentration = float(score_abs.max() / score_abs.sum()) if not score_abs.empty and float(score_abs.sum()) > 0 else np.nan
        rows.append({
            "테마": theme,
            "하위테마": subtheme,
            "종목수": int(len(group)),
            "대표주": f"{leader['종목명']} ({leader['Ticker']})",
            "1개월수익률": ret_1m,
            "3개월수익률": ret_3m,
            "이전3개월수익률": ret_prev_3m,
            "상대3개월수익률": np.nan,
            "6개월수익률": ret_6m,
            "가속도": accel,
            "상승종목비율": up_ratio,
            "거래량증가": volume_growth,
            "상위종목쏠림": concentration,
            "가격수준": price_level,
            "돈흐름점수": flow_score,
            "상태": classify_money_flow_state(ret_3m, ret_6m, accel),
            "추격위험": classify_chase_risk(price_level, ret_1m),
            "구성종목": ", ".join(group["종목명"].drop_duplicates().astype(str).tolist()),
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["히트맵크기"] = (df["3개월수익률"].abs().fillna(0) * 100).clip(lower=1)
    return apply_relative_money_flow_state(df, group_col="테마", score_col="돈흐름점수")


def calculate_image_theme_rotation_df(theme_flow_df):
    if theme_flow_df is None or theme_flow_df.empty:
        return pd.DataFrame()

    all_rows = theme_flow_df.copy()
    valid = all_rows.dropna(subset=["돈흐름점수"]).copy()
    if valid.empty:
        return pd.DataFrame()

    rows = []
    for theme, group in valid.groupby("테마", sort=False):
        total_count = int((all_rows["테마"] == theme).sum())
        leader = group.sort_values("돈흐름점수", ascending=False).iloc[0]
        weak = group.sort_values("돈흐름점수", ascending=True).iloc[0]
        ret_1m = group["1개월수익률"].mean()
        ret_3m = group["3개월수익률"].mean()
        ret_prev_3m = group["이전3개월수익률"].mean() if "이전3개월수익률" in group.columns else np.nan
        ret_6m = group["6개월수익률"].mean()
        accel = group["가속도"].mean()
        volume_growth = group["거래량증가"].mean() if "거래량증가" in group.columns else np.nan
        price_level = group["가격수준"].mean()
        up_ratio_1m = group["1개월수익률"].gt(0).mean()
        up_ratio_3m = group["3개월수익률"].gt(0).mean()
        up_ratio_6m = group["6개월수익률"].gt(0).mean()
        score_abs = group["돈흐름점수"].abs().dropna()
        concentration = float(score_abs.max() / score_abs.sum()) if not score_abs.empty and float(score_abs.sum()) > 0 else np.nan
        breadth_bonus = (up_ratio_3m - 0.5) * 20
        volume_bonus = (volume_growth if finite_num(volume_growth) else 0) * 6
        concentration_penalty = (concentration if finite_num(concentration) else 0) * 8
        theme_score = (
            (ret_1m if finite_num(ret_1m) else 0) * 18 +
            (ret_3m if finite_num(ret_3m) else 0) * 36 +
            (ret_6m if finite_num(ret_6m) else 0) * 22 +
            (accel if finite_num(accel) else 0) * 18 +
            breadth_bonus +
            volume_bonus -
            concentration_penalty
        )

        rows.append({
            "테마": theme,
            "종목수": total_count,
            "계산종목수": int(len(group)),
            "대표주": f"{leader['종목명']} ({leader['Ticker']})",
            "약세주": f"{weak['종목명']} ({weak['Ticker']})",
            "1개월수익률": ret_1m,
            "3개월수익률": ret_3m,
            "이전3개월수익률": ret_prev_3m,
            "상대3개월수익률": np.nan,
            "6개월수익률": ret_6m,
            "가속도": accel,
            "상승종목비율": up_ratio_3m,
            "1개월상승비율": up_ratio_1m,
            "6개월상승비율": up_ratio_6m,
            "거래량증가": volume_growth,
            "상위종목쏠림": concentration,
            "가격수준": price_level,
            "테마돈흐름점수": theme_score,
            "상태": classify_money_flow_state(ret_3m, ret_6m, accel),
            "추격위험": classify_chase_risk(price_level, ret_1m),
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["히트맵크기"] = (df["3개월수익률"].abs().fillna(0) * 100).clip(lower=1)
    return apply_relative_money_flow_state(df, score_col="테마돈흐름점수")


@st.cache_data(ttl=900, show_spinner=False)
def get_sector_flow_state(sector_bench_ticker: str) -> str:
    """단일 섹터 벤치마크 티커의 돈흐름 상태를 반환합니다."""
    if not sector_bench_ticker:
        return "-"
    data = download_money_flow_prices((sector_bench_ticker,))
    px = get_money_flow_ohlc(data, sector_bench_ticker)
    if px.empty or len(px) < 20:
        return "-"
    close = px["Close"]
    ret_3m = get_return_by_days(close, 63)
    ret_6m = get_return_by_days(close, 126)
    ret_prev_3m = get_return_by_days_offset(close, 63, offset=63)
    accel = ret_3m - ret_prev_3m if finite_num(ret_3m) and finite_num(ret_prev_3m) else np.nan
    return classify_money_flow_state(ret_3m, ret_6m, accel)

