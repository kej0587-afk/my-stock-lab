"""Find issuer-specific earnings leads in already collected, attributed news.

This is not an all-market calendar. A headline is never promoted to an official
release, its publication time is not an earnings announcement time, and its
numbers never become financial inputs.
"""

from copy import deepcopy
from datetime import timedelta
import re

from stock_lab_core.market_board_universe import STOCK_UNIVERSES
from stock_lab_core.asset_classifier import is_fin_score_exempt_asset
from stock_lab_core.report_build import register_loaded_source
from stock_lab_core.report_evidence import curate_news, first, is_held, records, stamp, text

register_loaded_source(__name__, __file__)

_ALIASES = {
    "GOOGL": ("Google", "구글", "알파벳"), "MSFT": ("마이크로소프트",),
    "AMZN": ("아마존",), "META": ("메타",), "TSLA": ("테슬라",),
    "NVDA": ("엔비디아",), "JPM": ("JP Morgan", "JPMorgan Chase", "JP모건", "제이피모건"),
    "LLY": ("일라이릴리", "일라이 릴리"), "JNJ": ("존슨앤드존슨", "존슨앤존슨"),
    "UNH": ("유나이티드헬스",), "WMT": ("월마트",), "CAT": ("캐터필러",),
    "XOM": ("엑슨모빌",), "CVX": ("셰브론",), "COST": ("코스트코",),
    "INTC": ("Intel", "인텔"), "SNDK": ("Sandisk", "샌디스크"),
}
_EARNINGS = re.compile(r"\b(?:earnings|quarterly results|financial results|EPS|guidance)\b|실적|가이던스|"
                       r"(?:매출|영업이익|순이익).{0,30}(?:발표|기록|전망|증가|감소)", re.I)
_PREVIEW = re.compile(r"\b(?:preview|will report|to report|ahead of|scheduled|(?:expected|forecast|anticipated) to|release date)\b|발표\s*예정|실적.{0,8}앞두|실적\s*프리뷰|예상\s*실적|실적\s*전망", re.I)
_RESULT = re.compile(r"\b(?:reports?|reported|announces?|announced|beats?|misses?|results)\b|"
                     r"실적.{0,14}(?:발표|상회|하회|부진|호조|실망)|(?:매출|영업이익|순이익).{0,25}(?:기록|발표)", re.I)
TOPICS = (
    ("capex", "설비투자", r"\bcapex\b|capital expenditur|capital spend|설비투자|자본지출"),
    ("free_cash_flow", "잉여현금흐름", r"\bFCF\b|free cash flow|잉여.?현금|현금흐름|현금 흐름"),
    ("guidance", "회사 전망", r"\bguidance\b|\boutlook\b|가이던스|실적 전망"),
    ("comparison", "예상 대비 보도", r"\b(?:beat|miss|consensus|estimates?)\b|예상|기대치|상회|하회"),
)


def canonical_ticker(value):
    symbol = text(value).upper()
    return {"GOOG": "GOOGL", "005930": "005930.KS", "005935": "005930.KS", "005935.KS": "005930.KS", "000660": "000660.KS"}.get(symbol, symbol)


def issuer_catalog(summary_rows=(), events=()):
    catalog = {ticker: dict(ticker=ticker, name=name, sector=sector, market=market,
                           aliases=[name, *_ALIASES.get(ticker, ())], held=False, registered=False)
               for market, rows in STOCK_UNIVERSES.items() for ticker, name, sector in rows}
    for row in [*records(events), *records(summary_rows)]:
        ticker = canonical_ticker(first(row, "ticker", "티커"))
        asset = text(first(row, "asset_class", "자산군")).lower()
        name = text(first(row, "종목명", "name", "종목", "event"))
        if (not re.fullmatch(r"[A-Z0-9][A-Z0-9.-]{0,19}", ticker)
                or is_fin_score_exempt_asset(ticker, row.get("is_etf", False), asset, name)
                or re.search(r"\bETF\b", name, re.I)):
            continue
        name = re.sub(r"\s+earnings(?: call)?$", "", name, flags=re.I).strip(" ,")
        entry = catalog.setdefault(ticker, dict(ticker=ticker, name=name or ticker, sector="업종 미연결",
            market="KR" if ticker.endswith((".KS", ".KQ")) else "US", aliases=list(_ALIASES.get(ticker, ())), held=False, registered=False))
        if name and name != ticker and len(name) <= 100:
            entry["aliases"] = list(dict.fromkeys([*entry["aliases"], name]))
        entry["held"] |= is_held(row)
        entry["registered"] |= not bool(row.get("event_status"))
    return catalog


def _name_match(title, entry):
    for name in entry["aliases"]:
        if len(name) < (3 if name.isascii() else 2):
            continue
        if re.search(r"(?<![\w])" + re.escape(name) + (r"(?![A-Za-z0-9])" if name.isascii() else r"(?![가-힣])"), title, re.I):
            return True
        # Korean particles follow company names without a word boundary.
        if not name.isascii() and re.search(re.escape(name) + r"(?:은|는|이|가|의|,|\s|$)", title):
            return True
    ticker = entry["ticker"]
    if entry["market"] == "US":
        # Short words (ON, V, MA, GE...) require explicit ticker notation.
        prefix = r"(?:\$|NASDAQ\s*:\s*|NYSE\s*:\s*)" if len(ticker) < 3 else r"(?<![A-Za-z0-9])"
        return bool(re.search(prefix + re.escape(ticker) + r"(?![A-Za-z0-9])", title))
    return False


def _earnings_subject(title, entry):
    """Require the lead earnings clause, not a partner mentioned later."""
    cue = _EARNINGS.search(title)
    prefix = re.sub(r"^(?:\[[^]]+\]\s*)+", "", title[:cue.start()]).strip()
    names = [*entry["aliases"], entry["ticker"]]
    for name in sorted(names, key=len, reverse=True):
        if not name:
            continue
        match = re.match(re.escape(name) + r"(?![A-Za-z0-9])", prefix, re.I)
        if not match:
            continue
        tail = prefix[match.end():]
        tail = re.sub(r"\b(?:FY)?20\d{2}\s*Q[1-4]\b|\bQ[1-4]\s*(?:FY)?20\d{2}\b|\b(?:FY)?20\d{2}\b|\bQ[1-4]\b|[1-4]분기|20\d{2}년", "", tail, flags=re.I)
        tail = re.sub(r"\b(?:will|to|reports?|reported|announces?|announced|first|second|third|fourth|quarter|quarterly|fiscal|year)\b", "", tail, flags=re.I)
        if not re.sub(r"(?:['’]s)|[\s,:·-]|^(?:은|는|이|가|의)", "", tail):
            return True
    return False


def discover_earnings_news(news, catalog, now):
    now = stamp(now)
    found, rejected, seen = [], {}, set()
    for raw in records(news)[:320]:
        title = text(raw.get("title"))[:2000]
        if not _EARNINGS.search(title):
            continue
        published = stamp(first(raw, "published_at", "published"))
        if not published or not now - timedelta(days=7) <= published <= now:
            continue
        valid = curate_news([raw], now=now, limit=1, title_pattern=_EARNINGS)
        if not valid:
            continue
        row = valid[0]
        key = row.get("link") or row["title"]
        if key in seen:
            continue
        seen.add(key)
        matches = [entry for entry in catalog.values() if _name_match(title, entry)]
        if len(matches) != 1:
            reason = "복수 기업·귀속 보류" if matches else "기업 매핑 미연결"
            rejected[reason] = rejected.get(reason, 0) + 1
            continue
        entry = matches[0]
        if not _earnings_subject(title, entry):
            rejected["실적 주체 불명확"] = rejected.get("실적 주체 불명확", 0) + 1
            continue
        if row.get("market") not in {None, "", entry["market"]}:
            rejected["시장 불일치"] = rejected.get("시장 불일치", 0) + 1
            continue
        fiscal = re.search(r"\b(FY)?(20\d{2})\s*Q([1-4])\b|\bQ([1-4])\s*(FY)?(20\d{2})\b", title, re.I)
        period = ""
        if fiscal:
            a, y, q, q2, a2, y2 = fiscal.groups()
            period = ("FY" if a or a2 else "") + (y or y2) + "Q" + (q or q2)
        phase = "preview" if _PREVIEW.search(title) else "result_report" if _RESULT.search(title) else "followup"
        found.append(dict(ticker=entry["ticker"], fiscal_period=period, phase=phase,
            published_at=published.isoformat(), article=deepcopy(row),
            topics=[key for key, _, pattern in TOPICS if re.search(pattern, title, re.I)]))
    return {"items": found, "excluded": rejected, "catalog_count": len(catalog), "input_limit": 320}
