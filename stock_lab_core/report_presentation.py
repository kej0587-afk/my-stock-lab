"""Display-only report checks; no score, threshold or execution overrides."""

import re
from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)

from datetime import datetime
from zoneinfo import ZoneInfo

from stock_lab_core.report_evidence import KST, first, macro_stress, number, stamp, text, _cell


def kst_time(value):
    dt = stamp(value)
    return dt.strftime("%Y-%m-%d %H:%M KST") if dt else "시각 미제공"


def oil_explanation(macro_data):
    oil = next((row for row in macro_stress(macro_data)["rows"] if row["name"] == "유가"), None)
    if not oil:
        return "유가 자료 미수집: 스트레스 기여도 확인 보류."
    value, points = oil["value"], oil["contribution"]
    if value >= 100:
        reason = "100달러 이상 수준 경고"
    elif value >= 90 and oil["direction"] == "하락" and points == 0:
        reason = "90~100달러 고수준 부담 유지, 하락 완화점수 미적용"
    else:
        reason = oil["state"] + " · " + oil["direction"]
    return f"현재 WTI {value:.2f}달러: {reason} → 유가 기여 {points:+d}점. 기존 산식·매매 임계값 유지."


def macro_change(previous, current):
    if not previous:
        return "스트레스 변화: 이전 매크로 스냅샷 없음(변화 원인 추정 안 함)."
    before, after = macro_stress(previous), macro_stress(current)
    if before["score"] is None or after["score"] is None:
        return "스트레스 변화: 산출 가능한 지표 부족으로 비교 보류."
    old = {row["name"]: row for row in before["rows"]}
    if set(old) != {row["name"] for row in after["rows"]}:
        return "스트레스 변화: 수집 지표 구성이 달라 동일 기준 비교 보류."
    parts = [f"스트레스 {before['score']}→{after['score']}: 구성요소별 비교(이전 저장 스냅샷 대비, 일간 변화 아님)", "",
             "지표 | 기준일 이전→현재 | 수준 이전→현재 | 1개월 변화율 이전→현재 | 기여 이전→현재 | 기여 Δ(점)",
             "--- | --- | --- | --- | --- | ---"]
    same_date_change = False
    for row in after["rows"]:
        prev = old[row["name"]]
        delta = row["contribution"] - prev["contribution"]
        changes = [f"{item['change']:+.2f}%" if item["change"] is not None else "미수집" for item in (prev, row)]
        parts.append(" | ".join(_cell(value) for value in (
            row["label"], f"{prev['as_of'] or '미제공'}→{row['as_of'] or '미제공'}",
            f"{prev['value']:.2f}→{row['value']:.2f}", "→".join(changes),
            f"{prev['contribution']:+d}→{row['contribution']:+d}", f"{delta:+d}")))
        same_date_change |= prev["as_of"] == row["as_of"] and any(
            prev[key] != row[key] for key in ("value", "change", "contribution"))
    if same_date_change:
        parts.append("\n동일 기준일 자료 변경 포함: 시장의 하루 변화로 해석 금지.")
    parts.append("\n기여 Δ 0은 가격 불변을 뜻하지 않습니다. 수준·1개월 방향에 따른 구간 점수이며, 0~100 제한으로 총점 변화가 가려질 수 있습니다. 신용 스프레드는 이 산식에 미포함입니다.")
    return "\n".join(parts)


def candidate_fields(row):
    ticker = text(first(row, "티커", "ticker"))
    name = text(first(row, "종목명", "name", "자산명")) or "종목명 미연결"
    raw_grade = text(first(row, "후보품질", "📌후보등급", "후보등급", "grade"))
    grade = re.search(r"[SABCF]급", raw_grade)
    quality = grade.group() if grade else "등급 미제공"
    gate = text(first(row, "게이트상태", "gate_state")) or "판단자료 미제공"
    reason = text(first(row, "게이트근거", "시장실행근거", "최종읽기"))
    code = " ".join(text(row.get(key)) for key in ("판정코드", "최종읽기", "게이트근거", "시장실행상태", "상위시간대상태"))
    checks = []
    if any(word in code for word in ("시장", "MARKET", "MACRO")):
        checks.append("해당 시장 신규매수 중단 해제 후 종목 게이트 재통과")
    if any(word in code for word in ("추세", "MTF", "STRUCTURE", "TREND", "상위 시간대 경고")):
        checks.append("일봉·주봉 추세훼손 해제 및 상위 시간대 경고 해소")
    if any(word in code for word in ("가격방어", "DRAWDOWN", "BREAKDOWN")):
        checks.append("가격 급락·지지 이탈 조건 해소 후 가격방어 게이트 재계산")
    if any(word in code for word in ("R/R", "손익비", "RR_")):
        checks.append("실제 목표·손절 재확인 후 손익비 게이트 통과")
    if any(word in code for word in ("비중", "OVERWEIGHT", "TARGET_FILLED")):
        checks.append("현재비중을 목표 범위 이내로 확인")
    if any(word in code for word in ("과열", "OVERHEAT")):
        checks.append("과열 조건 해소 및 종가 지지 확인")
    explicit = text(first(row, "해제조건", "다음확인"))
    condition = explicit or " / ".join(checks) or "구체 해제 조건 미제공: 상세 게이트 근거 재확인"
    action = "실행가능" if gate in {"실행가능", "EXECUTABLE"} else "게이트로 보류"
    return (f"{name}({ticker}) · 개별 신호 {quality}, {action}({gate})", reason or "미제공", condition)


def candidate_line(row):
    label, reason, condition = candidate_fields(row)
    return f"- {label} · 근거: {reason} · 해제 조건: {condition}"


def account_metrics(held, observations, sessions):
    """Weight times actual asset return, never leverage an ETF's return twice."""
    from stock_lab_core.report_holdings import UNDERLYINGS
    from stock_lab_core.portfolio import infer_scenario_shock_multiplier

    daily, gap, coverage, gap_coverage = 0.0, 0.0, 0.0, 0.0
    by_market = {"US": 0.0, "KR": 0.0}
    replacement, replacement_coverage, concentration = 0.0, 0.0, 0.0
    seen = set()
    for row in held:
        ticker = text(first(row, "티커", "ticker")).upper()
        weight = number(first(row, "현재비중", "current_w"))
        if ticker in seen or weight is None or not 0 <= weight <= 100:
            return {"error": "중복 종목 또는 비중 결측·범위 오류"}
        seen.add(ticker)
        obs = observations.get(ticker, {})
        region = "KR" if ticker.endswith((".KS", ".KQ")) else "US"
        move = number(obs.get("return"))
        valid_move = move is not None and obs.get("date") == sessions.get(region) and sessions.get(region)
        if valid_move:
            daily += weight * move
            by_market[region] += weight * move
            coverage += weight
        if ticker.split(".")[0] in {"379800", "379810", "418660"}:
            concentration += weight
            for base in UNDERLYINGS[ticker.split(".")[0]]:
                proxy = observations.get(base, {})
                change = number(proxy.get("return"))
                if change is not None and sessions.get("US") and proxy.get("date") == sessions["US"] and sessions.get("KR", "") <= sessions["US"]:
                    mult = infer_scenario_shock_multiplier({"티커": ticker, "자산명": text(first(row, "종목명", "name"))})
                    gap += weight * change * mult
                    gap_coverage += weight
                    replacement += weight * change * mult
                    replacement_coverage += weight
                    break
        elif region == "KR" and (ticker.split(".")[0] in {"0167A0", "0227L0"} or "미국" in text(first(row, "종목명", "name"))):
            # No numerical scenario for a concentrated basket without its constituents.
            continue
        elif valid_move:
            replacement += weight * move
            replacement_coverage += weight
    if coverage > 100.01 or sum(number(first(row, "현재비중", "current_w")) or 0 for row in held) > 100.01:
        return {"error": "현재비중 합계가 100% 초과"}
    if not coverage:
        return {"error": "비중과 같은 시장 기준일의 등락 미연결"}
    return dict(daily=daily, gap=gap, coverage=coverage, gap_coverage=gap_coverage,
                replacement=replacement, replacement_coverage=replacement_coverage,
                concentration=concentration, by_market=by_market)


def account_headline(metrics, sessions, mode):
    metrics = metrics or {}
    if not metrics or metrics.get("error"):
        return "계좌 추정 보류: " + metrics.get("error", "보유자료 미연결")
    if metrics["coverage"] < 90:
        return f"계좌 추정 보류: 종가 연결 비중 {metrics['coverage']:.1f}%로 90% 미만"
    split = metrics.get("by_market")
    detail = (f" · 미국 상장 {split['US']:+.2f}%p / 한국 상장 {split['KR']:+.2f}%p"
              if split else "")
    return (f"최신 종가 기준 계좌 추정 {metrics['daily']:+.2f}%p(연결 비중 {metrics['coverage']:.1f}%; "
            f"미국 {sessions.get('US', '미확인')} / 한국 {sessions.get('KR', '미확인')})" + detail)


def account_live_estimate(held, live):
    """Separate a live US contribution from the closed-price account headline."""
    from stock_lab_core.portfolio import infer_scenario_shock_multiplier
    from stock_lab_core.report_holdings import UNDERLYINGS

    us, gap, us_weight, gap_weight = 0.0, 0.0, 0.0, 0.0
    dates, times = set(), []
    for row in held:
        ticker = text(first(row, "티커", "ticker")).upper()
        weight = number(first(row, "현재비중", "current_w"))
        if weight is None or not 0 <= weight <= 100:
            continue
        domestic = ticker.split(".")[0] in {"379800", "379810", "418660"}
        bases = UNDERLYINGS.get(ticker.split(".")[0], ()) if domestic else (ticker,)
        for base in bases:
            obs = live.get(base, {})
            move = number(obs.get("return"))
            if move is None or not obs.get("date"):
                continue
            dates.add(obs["date"])
            times.append(kst_time(obs.get("as_of", obs.get("retrieved_at"))))
            if domestic:
                mult = infer_scenario_shock_multiplier({"티커": ticker, "자산명": text(first(row, "종목명", "name"))})
                gap += weight * move * mult
                gap_weight += weight
            elif not ticker.endswith((".KS", ".KQ")):
                us += weight * move
                us_weight += weight
            break
    if not dates:
        return ""
    time_range = min(times) if min(times) == max(times) else f"{min(times)}~{max(times)}"
    return (f"미국 {', '.join(sorted(dates))} 장중 별도 추정(확정 아님): 미국 보유분 기여 {us:+.2f}%p(비중 {us_weight:.1f}%), "
            f"다음 한국장 미국지수 ETF 갭 시나리오 기여 {gap:+.2f}%p(비중 {gap_weight:.1f}%). "
            f"시세 {time_range} · 종가 계좌 추정과 합산 금지, 환율·선물·추적오차 미반영.")


def account_estimate(held, observations, sessions, *, mode="preopen"):
    metrics = account_metrics(held, observations, sessions)
    if metrics.get("error"):
        return "계좌 합계(추정) 보류: " + metrics["error"] + "."
    daily, gap = metrics["daily"], metrics["gap"]
    coverage, gap_coverage = metrics["coverage"], metrics["gap_coverage"]
    main = account_headline(metrics, sessions, mode) + ". "
    if mode == "preopen" and metrics["replacement_coverage"] < 90:
        main += (f"장전 대체 합산은 연결 비중 {metrics['replacement_coverage']:.1f}%로 헤드라인 제외. "
                 + ("한국 최신 종가가 미국 기준일보다 뒤여서 이미 반영된 국내 미국지수 ETF를 장전 값으로 다시 치환하지 않음. "
                    if sessions.get("KR", "") > sessions.get("US", "") else "기초자산·갭 수치 미연결분 제외. "))
    note = f"계좌 일간 기여 합계(추정): {daily:+.2f}%p · 연결 비중 {coverage:.1f}%"
    if gap_coverage and mode == "preopen":
        note += f" / 한국 상장 미국자산 ETF 개장 전 갭 시나리오 기여(추정): {gap:+.2f}%p · 적용 비중 {gap_coverage:.1f}%"
    return (main + note + f" · 379810/379800/418660 집중도 {metrics['concentration']:.1f}%. "
            "현재비중 가중, 현금·미연결분 제외, 환율·거래 미반영."
            + (" 갭 미연결 종목은 대체 합산에서 제외. 일간 합계와 갭 기여를 단순 합산하지 않음."
               if mode == "preopen" else ""))


def news_theme(title):
    title = text(title)
    if re.search(r"(?<![A-Za-z])AI(?![A-Za-z])|인공지능|CoreWeave|코어위브", title, re.I):
        easing = re.search(r"(?:우려|불안).{0,8}(?:완화|해소)|(?:worr\w*|fear\w*|concern\w*).{0,15}(?:abat|eas|fad|reced)", title, re.I)
        if easing and re.search(r"신용|\bcredit\b", title, re.I):
            return "AI 신용우려 완화"
        if easing and re.search(r"차입|부채|\bdebt\b|\bborrowing\b", title, re.I):
            return "AI 차입우려 완화"
    for pattern, label in (
        (r"AI\s*신용\s*(?:우려|위험|리스크)", "AI 신용우려"),
        (r"AI\s*(?:차입|부채)\s*우려", "AI 차입 우려"),
        (r"AI\s*투자\s*(?:불안|우려)", "AI 투자 불안"),
    ):
        if re.search(pattern, title, re.I):
            return label
    ai = r"(?<![A-Za-z])AI(?![A-Za-z])|artificial intelligence|인공지능|코어위브|\bCoreWeave\b|네오클라우드|\bneoclouds?\b"
    if re.search(ai, title, re.I):
        concern = bool(re.search(r"우려|불안|위험|부담|worr|fear|concern|risk|crunch|jitters|burden", title, re.I))
        for pattern, label in (
            (r"신용|\bcredit\b", "AI 신용우려" if concern else "AI 신용 관련 보도"),
            (r"차입|부채|빚|\bdebt\b|\bborrowing\b|\bleverage[d]?\b", "AI 차입 우려" if concern else "AI 차입·부채"),
            (r"자금\s*조달|금융\s*조달|\bfinanc(?:e|es|ing)\b|\bfunding\b|\bbonds?\b", "AI 자금조달"),
            (r"투자.{0,8}(?:불안|우려)|(?:capex|spending|investment).{0,30}(?:worr|fear|concern|risk)", "AI 투자 불안"),
            (r"코어위브|\bCoreWeave\b|네오클라우드|\bneoclouds?\b", "AI 인프라 관련 보도"),
            (r"반등|\brebound|\bbounc|\brecover", "AI 관련주 반등"),
        ):
            if re.search(pattern, title, re.I):
                return label
    return ""


# The same exposure vocabulary drives report searches and title matching.
_SECTOR_NEWS_PROFILES = {
    "semiconductor": ("SOXX SMH SOXL SOXS 396500.KS", r"반도체|semiconductor|\bchips?\b|\bSOXX\b|\bSMH\b|NVIDIA|엔비디아|삼성전자|SK\s*하이닉스", "반도체 OR 삼성전자 OR SK하이닉스", "semiconductor stocks OR chip stocks"),
    "memory": ("DRAM MU", r"메모리|\bDRAM\b|\bHBM\b|Micron|마이크론|SK\s*하이닉스", "메모리 OR DRAM OR HBM", "memory stocks OR Micron OR DRAM"),
    "technology": ("XLK QQQ TQQQ SQQQ TECL TECS FNGU FNGD", r"기술주?|빅테크|테크|FANG|\btechnology\b|\btech\b|\bXLK\b", "기술주 OR 빅테크 OR AI", "technology stocks OR big tech"),
    "software": ("IGV", r"소프트웨어|software|사이버|cyber|\bIGV\b", "소프트웨어 OR 사이버보안", "software stocks OR cybersecurity stocks"),
    "energy": ("XLE ERX ERY 139250.KS", r"에너지|energy|정유|석유|원유|유가|\boil\b|\bWTI\b|\bBrent\b|\bOPEC\b|\bXLE\b", "에너지주 OR 정유 OR 유가", "energy stocks OR oil prices OR oil producers"),
    "utilities": ("XLU", r"유틸리티|utilities|전력|전기료|\bXLU\b", "전력 OR 유틸리티", "utilities stocks OR power demand"),
    "communications": ("XLC VOX", r"통신|communication services|telecom|미디어|media stocks|광고|advertising|\bMeta\b|Alphabet|\bXLC\b", "통신주 OR 미디어 OR 광고", "communication services stocks OR telecom stocks OR Meta earnings"),
    "consumer": ("XLY XLP VCR VDC", r"소비재|소비주|소비심리|소매|유통|음식료|consumer|retail|staples|\bXLY\b|\bXLP\b", "소비재 OR 소매판매 OR 유통", "consumer stocks OR retail sales OR consumer staples"),
    "healthcare": ("XLV VHT", r"헬스케어|건강|의료|제약|health\s*care|pharma|\bXLV\b|\bVHT\b", "헬스케어 OR 의료 OR 제약", "healthcare stocks OR pharma stocks"),
    "biotech": ("XBI IBB LABU LABD", r"바이오|생명과학|biotech|임상|clinical trial|FDA|백신|vaccine|\bXBI\b|\bIBB\b", "바이오 OR 임상 OR 제약", "biotech stocks OR clinical trial OR FDA approval"),
    "cosmetics": ("", r"화장품|뷰티|cosmetics|beauty|아모레|Amorepacific|LG생활건강", "화장품 OR 뷰티 OR 아모레퍼시픽", "cosmetics stocks OR beauty sales"),
    "battery": ("LIT BATT 305540.KS", r"2차전지|이차전지|배터리|리튬|양극재|음극재|battery|batteries|lithium|cathode|\bLIT\b|\bBATT\b", "2차전지 OR 배터리 OR 리튬", "battery stocks OR lithium stocks OR electric vehicle batteries"),
    "financials": ("XLF KRE KBE", r"금융|은행|증권|보험|financials|banks?|banking|insurance|\bXLF\b", "금융주 OR 은행 OR 증권", "financial stocks OR bank stocks"),
    "industrials": ("XLI", r"산업재|기계|건설|인프라|industrials|infrastructure|\bXLI\b", "산업재 OR 기계 OR 건설", "industrial stocks OR infrastructure"),
}


def sector_news_topics(ticker, *, sector_name=""):
    """Return stable topic keys for symbols or full Korean ETF product names."""
    symbol = text(ticker).upper()
    sector_name = text(sector_name)
    return tuple(key for key, (symbols, pattern, _, _) in _SECTOR_NEWS_PROFILES.items()
                 if symbol in symbols.split() or (sector_name and re.search(pattern, sector_name, re.I)))


def sector_news_query(topic, market):
    profile = _SECTOR_NEWS_PROFILES[topic]
    return profile[2 if market == "KR" else 3]


def market_cause_candidates(news, market, session):
    """Retrospective claims may supply candidates, never proof of a price cause."""
    if not session:
        return []
    zone = KST if market == "KR" else ZoneInfo("America/New_York")
    close = datetime.fromisoformat(session).replace(
        hour=15 if market == "KR" else 16, minute=30 if market == "KR" else 0, tzinfo=zone)
    candidates, seen = [], set()
    for row in news:
        title = text(row.get("title"))
        topic = news_theme(title)
        published = stamp(first(row, "published_at", "published"))
        if (not topic or topic in seen or not row.get("link") or not published
                or row.get("market") != market or row.get("session_date") != session
                or row.get("news_bucket") in {"next_session_news", "other_market_news"}
                or is_preopen_outlook(row) or is_preopen_price_recap(row) or published.astimezone(zone).date() != close.date()):
            continue
        if row.get("news_bucket") == "current_session_news" and re.search(r"마감|\bclos(?:ed|ing)\b|\bmarket wrap\b", title, re.I):
            continue
        if published > close and not (row.get("retrospective_close_wrap") or row.get("is_close_wrap")
                                      or re.search(r"마감|close", title, re.I)):
            continue
        seen.add(topic)
        candidates.append(row)
    return candidates[:2]


def is_preopen_outlook(row):
    """Identify a market forecast by content, independent of publication hour."""
    title = text(row.get("title"))
    if re.search(r"\b(?:stocks?|index|equity|Wall Street|Nasdaq|Dow Jones|S&P(?:\s*500)?) futures\b|\bpre[- ]?market\b|\bahead of (?:the )?open\b|"
                 r"\b(?:market|stocks?|wall street) (?:outlook|preview)\b|"
                 r"\bstocks? (?:are )?(?:set|poised|expected) to\b|뉴욕증시\s*전망|미국\s*증시\s*전망", title, re.I):
        return True
    if row.get("market") != "KR":
        return False
    if re.search(r"장전\s*전망|\[(?:장전|증시전망|오늘의?\s*증시)\]", title):
        return True
    if re.search(r"\[마감\]|(?:코스피|코스닥|한국\s*증시).{0,60}마감", title):
        return False
    return bool(re.search(r"개장\s*전|장\s*시작\s*전", title)) or (row.get("news_timing") in {"장전 보도", "장전전망(결과와 다름)"}
            and bool(re.search(r"코스피|코스닥|(?:한국|국내)\s*증시", title))
            and bool(re.search(r"전망|예상", title)))


def is_preopen_price_recap(row):
    """A pre-open market-price recap cannot describe that regular session."""
    published = stamp(first(row, "published_at", "published"))
    session = text(row.get("session_date"))
    market = row.get("market")
    if not published or not session or market not in {"KR", "US"}:
        return False
    zone = KST if market == "KR" else ZoneInfo("America/New_York")
    opening = datetime.fromisoformat(session).replace(hour=9, minute=0 if market == "KR" else 30, tzinfo=zone)
    if published >= opening:
        return False
    title = text(row.get("title"))
    subject = re.search(r"코스피|코스닥|증시|\bstocks?\b|\bshares\b|Nasdaq|Wall Street|S&P\s*500", title, re.I)
    movement = re.search(r"반등|급등|급락|하락|상승|회복|\brebound|\brecover|\bbounc|\brall|\brise|\brises|\bgain|\bfall|\bdeclin|\bslump|\bsell.?off", title, re.I)
    return bool(subject and movement)


def compact_holding_reference(value):
    """Move only known shared limitations to the table note; keep hedge specifics."""
    for phrase in (
        " / 괴리율: 같은 시각 NAV·iNAV 미연결. 관측 등락이며 차이의 기여도 분해·합산은 아님.",
        "시가 갭 오차가 아닌 종가 등락과의 비교, 환율·선물 미반영",
        "환율·선물·추적오차 미반영, 확정 갭/가격 예측 아님",
        "환율·선물·추적오차 미반영",
        " 레버리지·환헤지 효과를 동일 배수로 추정하지 않음.",
    ):
        value = value.replace(phrase, "")
    return value.rstrip(" ·.")


def korean_market_catalysts(news, session):
    """Headline claims from the matching Korean session, not causal attribution."""
    parts = []
    for item in news:
        if (item.get("market") != "KR" or item.get("session_date") != session
                or item.get("news_bucket") in {"next_session_news", "other_market_news"}
                or is_preopen_outlook(item) or is_preopen_price_recap(item)):
            continue
        title = text(item.get("title"))
        if not re.search(r"코스피|코스닥|한국\s*증시", title):
            continue
        label = news_theme(title)
        if re.search(r"(?:外人|외인|외국인).{0,8}기관.{0,8}(?:동반\s*)?매도", title):
            label = "외국인·기관 동반 매도"
        if label and not any(label == prior[0] for prior in parts):
            parts.append((label, text(first(item, "publisher", "source"))))
    return " / ".join(f"{label}({publisher or '출처 미제공'})" for label, publisher in parts[:2])


def sector_related_news(ticker, session, news, *, sector_name=""):
    """Keep sector reports, common themes and other-market context distinct."""
    ticker = text(ticker).upper()
    region = "KR" if ticker.endswith((".KS", ".KQ")) else "US"
    topics = sector_news_topics(ticker, sector_name=sector_name)
    patterns = [_SECTOR_NEWS_PROFILES[topic][1] for topic in topics]
    if not patterns and sector_name:
        patterns = [re.escape(sector_name.removeprefix("한국 ").strip())]
    ai_exposure = bool(set(topics) & {"semiconductor", "memory", "technology", "software"})
    matched = []
    for item in news:
        title = text(item.get("title"))
        if re.search(r"日증시|일본\s*증시|중국\s*증시|대만\s*증시|Asian (?:shares|stocks)|Japan(?:ese)? (?:shares|stocks)|Chinese (?:shares|stocks)", title, re.I):
            continue
        if (not session or item.get("market") != region or item.get("session_date") != session
                or item.get("news_bucket") in {"next_session_news", "other_market_news"}
                or is_preopen_outlook(item) or is_preopen_price_recap(item)):
            continue
        # A wrongly tagged or hand-supplied row must not bypass market checks.
        cross_market_recap = bool(region == "US" and item.get("retrospective_close_wrap")
                                  and item.get("news_bucket") == "session_news"
                                  and re.search(r"코스피|코스닥", title)
                                  and re.search(r"(?:美|미국|뉴욕|Wall Street).{0,15}(?:AI|반도체|semiconductor).{0,30}(?:급락|selloff|slump)", title, re.I))
        if (region == "US" and not cross_market_recap
                and re.search(r"코스피|코스닥|한국\s*증시|국내\s*증시|삼전닉스|삼성전자|SK\s*하이닉스|CXMT|창신|한국 메모리|Korea.*(?:density|yield)", title, re.I)):
            continue
        if region == "KR" and re.search(r"(?:美|미국|뉴욕)\s*증시|\bWall Street\b|\bU\.?S\.?\s+stocks", title, re.I):
            continue
        published = stamp(first(item, "published_at", "published"))
        if published:
            zone = KST if region == "KR" else ZoneInfo("America/New_York")
            local = published.astimezone(zone)
            if local.date().isoformat() != session:
                from stock_lab_core.today_news import _us_close_recap
                close = datetime.fromisoformat(session).replace(hour=16, tzinfo=zone)
                if region != "US" or not _us_close_recap(title, published, {"end": close.isoformat()}):
                    continue
            if item.get("news_bucket") == "current_session_news" and re.search(r"마감|\bclos(?:ed|ing)\b|\bmarket wrap\b", title, re.I):
                continue
        direct = any(re.search(pattern, title, re.I) for pattern in patterns)
        theme = news_theme(title)
        common_ai = ai_exposure and bool(theme or re.search(r"(?<![A-Za-z])AI(?![A-Za-z])|인공지능", title, re.I))
        if region == "KR":
            market_context = bool(re.search(r"코스피|코스닥", title) and
                                  (theme or re.search(r"매도|매수|급락|반등", title)))
        else:
            market_context = common_ai
        # Financing headlines describe a shared AI investment background even
        # when the title also names chips or technology shares.
        financing_theme = bool(theme and re.search(r"신용|차입|자금조달|투자 불안|인프라", theme))
        if direct or market_context:
            indirect = cross_market_recap or bool(item.get("market_context_only")) or not direct or (common_ai and financing_theme)
            matched.append(dict(item, ticker=ticker, market_context_only=indirect,
                                news_relation="related_cross_market" if cross_market_recap else "market_common_theme" if indirect else "sector_report",
                                sector_news_topics=list(topics),
                                exposure_theme_context=common_ai and region == "US"))
    seen = set()
    unique = []
    for item in sorted(matched, key=lambda item: (bool(item.get("market_context_only")),
                                                 not bool(news_theme(text(item.get("title")))))):
        key = text(first(item, "link", "title"))
        if key and key not in seen:
            seen.add(key)
            unique.append(item)
    return unique
