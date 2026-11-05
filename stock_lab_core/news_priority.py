"""Editorial urgency only; never a trading score or causal claim."""

import re
import math
from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)


def market_news_priority(row):
    title = str(row.get("title") or row.get("제목") or "")
    if re.search(r"공시담당자|워크숍|채용공고|업무협약|시세표|^\s*\[표\]", title):
        return -100
    patterns = ((r"사이드카|서킷브레이커|circuit.breaker|trading.halt", 60),
                (r"중간선거|개표|블루웨이브|\bmidterms?\b|election results|blue wave", 25),
                (r"급락|폭락|급등|plung|crash|sell.off|slump", 25),
                (r"금리|FOMC|연준|일본은행|BOJ|rate (?:cut|hike|decision)", 20),
                (r"실적|가이던스|잉여현금|설비투자|earnings|guidance|capex|free cash flow", 15))
    return sum(score for pattern, score in patterns if re.search(pattern, title, re.I))


def editorial_priority(row, context=None):
    """Shared reading priority, not an investment score or proof of causation.

    Only same-market, same-session observed moves can increase relevance.
    A fuller closing account outranks an earlier index flash for that session.
    """
    context = context or {}
    title = str(row.get("title") or "")
    score = market_news_priority(row)
    if score < 0:
        return score
    market, session = row.get("market"), row.get("session_date")
    broad = bool(re.search(r"코스피|코스닥|KOSPI|KOSDAQ" if market == "KR" else
                          r"뉴욕증시|나스닥|S&P\s*500|Wall Street|Nasdaq", title, re.I))
    broad &= not bool(re.search(r"특징주|상장|장초반|전망|출발|개장|주간|[?？]", title))
    if broad:
        score += 35
        if re.search(r"종합|마감|market close", title, re.I):
            score += 45
        if re.search(r"속보|\[표\]", title):
            score -= 20
    target = context.get("sessions", {}).get(market)
    if isinstance(target, dict):
        target = target.get("date")
    current = context.get("current_sessions", {}).get(market, {})
    if isinstance(current, dict):
        current = current.get("date")
    if session and session in (target, current):
        score += 20
        from stock_lab_core.report_presentation import sector_news_topics
        topics = set(sector_news_topics("", sector_name=title))
        moves = []
        for asset in context.get("sector_rows", ()):
            ticker = str(asset.get("Ticker") or asset.get("ticker") or "")
            region = "KR" if ticker.endswith((".KS", ".KQ")) or ticker in {"^KS11", "^KQ11"} else "US"
            if region != market or str(asset.get("기준일") or asset.get("date") or "") != session:
                continue
            linked = broad or bool(ticker and ticker in title) or bool(topics & set(sector_news_topics(ticker, sector_name=str(asset.get("섹터") or ""))))
            try:
                move = float(asset.get("1일수익률", asset.get("return")))
            except (TypeError, ValueError):
                continue
            if linked and math.isfinite(move):
                moves.append(abs(move))
        # Returns are decimal fractions, matching the report price contract.
        if moves:
            score += min(60, int(max(moves) * 1000))
    return score
