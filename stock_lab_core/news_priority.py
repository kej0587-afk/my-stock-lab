"""Editorial urgency only; never a trading score or causal claim."""

import re
from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)


def market_news_priority(row):
    title = str(row.get("title") or row.get("제목") or "")
    if re.search(r"공시담당자|워크숍|채용공고|업무협약|시세표|^\s*\[표\]", title):
        return -100
    patterns = ((r"사이드카|서킷브레이커|circuit.breaker|trading.halt", 60),
                (r"급락|폭락|급등|plung|crash|sell.off|slump", 25),
                (r"금리|FOMC|연준|일본은행|BOJ|rate (?:cut|hike|decision)", 20),
                (r"실적|가이던스|잉여현금|설비투자|earnings|guidance|capex|free cash flow", 15))
    return sum(score for pattern, score in patterns if re.search(pattern, title, re.I))
