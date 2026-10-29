"""Post-close company evidence kept separate from the preceding market close."""

from stock_lab_core.catalyst_news import after_close_catalysts
from stock_lab_core.report_build import register_loaded_source
from stock_lab_core.report_evidence import _cell, citation, curate_news, records
from stock_lab_core.report_presentation import kst_time

register_loaded_source(__name__, __file__)


def post_close_brief(context, news, summary_rows, now):
    windows = records(context.get("windows"))
    end = next((row.get("end") for row in windows if row.get("market") == "US"
                and row.get("date") == context.get("sessions", {}).get("US")), None)
    validated = []
    # Validate each source without adding a quota or deduplication before selection.
    for row in [*records(news), *records(context.get("next_session_news"))]:
        validated.extend(curate_news([row], now=now, limit=1))
    items = after_close_catalysts(
        validated,
        closed_end=end, now=now, exposures=records(summary_rows), limit=3,
    )
    if not items:
        return {"overview": "", "lines": [], "article_keys": []}
    overview = "미국 종가 이후 별도 재료: " + " / ".join(item["summary"] for item in items[:2])
    has_capex = any("capex_cash_flow" in item["topics"] for item in items)
    if has_capex:
        overview += ". 성장 투자와 현금 창출력의 균형을 투자자가 재평가하는 쟁점입니다(보도 기반 해석)"
    overview += ". 앞선 정규장 등락 원인으로 소급하지 않습니다. 아래 출처와 시간외 시세를 구분해 확인합니다."
    lines = ["", "**미국 종가 이후 · 기업 실적과 투자자 반응**",
             "보도시각 | 기업 재료·출처 | 확인할 쟁점", "--- | --- | ---"]
    keys = []
    for item in items:
        sources = item["sources"]
        detail = item["summary"] + " · " + ("본문 확인" if item["evidence_level"] == "verified_body" else "제목 기준·기사 주장")
        detail += " · " + " / ".join(citation(row) for row in sources[:2])
        check = ("실적 증가와 별도로 CAPEX·영업현금흐름·FCF 및 회사 전망을 함께 비교"
                 if "capex_cash_flow" in item["topics"] else
                 "공식 실적·전망 및 해당 기업 시간외 가격 확인")
        if item["constituent_links"]:
            mapping = item["constituent_links"][0]
            check += f" · {mapping['etf']} 편입기업 간접 재료({mapping['holdings_as_of']} 구성 기준), ETF 하락 기여도 미확인"
        if "options_activity" in item["topics"]:
            check += " · 풋/콜 거래만으로 순매도·하락 원인 확정 불가"
        lines.append(" | ".join(_cell(value) for value in (kst_time(item["published_at"]), detail, check)))
        keys.extend(item["source_keys"])
    lines += ["", "정규장 마감 결과와 이후 실적·시간외 반응은 서로 다른 시간창입니다. 기사 주장만으로 시장 전체 하락 원인이나 구성종목별 ETF 기여도를 확정하지 않습니다."]
    return {"overview": overview, "lines": lines, "article_keys": list(dict.fromkeys(keys))}
