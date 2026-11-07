"""A short reading path over collected evidence; no requests, scores or forecasts."""

import re

from stock_lab_core.report_build import register_loaded_source
from stock_lab_core.report_evidence import _cell, citation, first, is_held, number, records, stamp, text

register_loaded_source(__name__, __file__)


def editorial_lines(context, synthesis, summary_rows, states, now):
    from stock_lab_core.article_context import verified_body_facts
    from stock_lab_core.report_brief import ENTITIES, _holding_links, brief_theme
    from stock_lab_core.report_intraday import _latest_observation

    lines = ["", "## 핵심 해석", ""]
    checked = max(now, stamp(context.get("quote_checked_at")) or now)
    observations = []
    for market, ticker in (("KR", "^KS11"), ("US", "^IXIC")):
        group, obs = _latest_observation(ticker, market, context, states, checked)
        # During an open session, do not build a current thesis from yesterday.
        if states[market]["phase"] == "intraday" and group != market:
            obs = {}
        observations.append(obs)
    kr, us = observations
    kr_ret, us_ret = number(kr.get("return")), number(us.get("return"))
    if kr_ret is not None and us_ret is not None and kr_ret * us_ret < 0:
        lines += ["**시장 판독: 한국과 미국의 방향이 엇갈렸습니다.** "
                  f"코스피 {kr_ret * 100:+.2f}%({kr['date']})와 나스닥 {us_ret * 100:+.2f}%({us['date']})는 "
                  "동시에 마감한 결과가 아닙니다. 한 시장의 방향을 설명하는 보도를 다른 시장의 반대 방향 움직임에도 그대로 적용할 수 없습니다. "
                  "[근거: 시장별 기준일·지수 관측]", ""]
    # Existing synthesis already checks market, session and source attribution.
    if synthesis.get("headline"):
        lines += [synthesis["headline"], ""]
    held = [row for row in records(summary_rows) if is_held(row)]
    selected, topics, urls = [], set(), set()
    for row in synthesis.get("background_news", []):
        at = stamp(first(row, "published_at", "published"))
        if not at or at > now or not 0 <= (now - at).total_seconds() <= 7 * 86400:
            continue
        source = citation(row)
        if not source or row.get("link") in urls:
            continue
        for fact in verified_body_facts(row):
            topic = fact.get("topic")
            if topic in topics or not all(text(fact.get(k)) for k in ("summary", "implication", "check")):
                continue
            title = text(row.get("title")) + " " + text(fact["summary"])
            entities = [ticker for ticker, pattern in ENTITIES if re.search(pattern, title, re.I)]
            holdings = _holding_links(held, title, entities, brief_theme(row), row.get("market"))
            selected.append((fact, row, holdings, source))
            topics.add(topic)
            urls.add(row.get("link"))
            break
        if len(selected) == 3:
            break
    if selected:
        lines += ["**근거에서 계좌까지**", "확인된 보도·시점 | 전달 경로·해석(추정) | 보유 연결·확인할 조건", "--- | --- | ---"]
        for fact, row, holdings, source in selected:
            basis = f"{row.get('market', '')} {row.get('session_date', '')} 세션"
            lines.append(" | ".join(_cell(v) for v in (
                fact["summary"] + " · " + basis + " " + source,
                fact["implication"], holdings + " · " + fact["check"])))
        lines += ["", "본문이 확인돼도 보도자의 해석은 기사 주장입니다. 보유 연결은 업종 노출이며 실제 손익 기여도·매매 신호가 아닙니다."]
    else:
        lines += ["본문 근거로 연결할 전달 경로가 부족합니다. 제목만으로 원인을 확정하지 않으며, 아래 핵심 재료의 확인 수준을 함께 봅니다."]
    lines += ["", "**다음 관측에서 해석을 바꿀 조건**",
              "확인할 축 | 해석을 지지하는 관측 | 반대 관측·보류 조건", "--- | --- | ---"]
    if kr_ret is not None and us_ret is not None and kr_ret * us_ret < 0:
        lines.append("한·미 방향 차이 | 다음 한국 거래일에도 미국 업종 흐름과 같은 방향으로 반영되는지 | 한국 수급·환율·종목별 차이가 남으면 미국 움직임만으로 한국의 다음 방향을 단정하지 않음")
    if topics & {"ai_credit", "ai_investment"}:
        lines.append("AI 투자와 회수 | 다음 공식 실적에서 투자 집행과 고객 매출·영업현금흐름 개선을 함께 확인 | 발주 축소·조달 부담 확대 또는 투자 후 현금흐름 악화가 확인되면 수요 기대와 회수 위험을 다시 분리")
    if topics & {"foreign_buying", "institution_buying"}:
        lines.append("수급의 지속성 | 다음 거래일에도 같은 투자자 순매수가 이어지는지 | 하루 순매수만으로 매수 동기·프로그램 매매·추세 반전을 확정하지 않음")
    lines.append("가격과 위험 | 다음 확정 종가의 업종 확산·변동성을 현재 기준일과 비교 | 하루 반등만 있거나 매크로 부담이 남으면 추세 회복 결론 보류")
    lines += ["", "확인 조건은 검토 질문이며 임계값·목표가가 아닙니다. 장기 적정가·현금 소진 시점은 별도 가정 모형 없이 계산하지 않습니다.", ""]
    return lines


def reading_order(lines):
    """Move explanations ahead of audit tables without dropping any section."""
    from stock_lab_core.report_view import split_report_sections
    sections = split_report_sections("\n".join(lines))
    priority = {title: i for i, title in enumerate(("", "기준일", "지금 상태 3줄", "핵심 해석",
        "MSFT 사업·투자 점검", "내 보유 종목 영향", "다가오는 일정", "오늘의 시장 스토리", "오늘의 핵심 재료", "지수·매크로 한눈에"))}
    return "".join(content for title, content in sorted(sections, key=lambda part: priority.get(part[0], 99))).split("\n")
