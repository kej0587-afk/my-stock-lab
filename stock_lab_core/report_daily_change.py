"""Today's market reading: key change -> reported background -> flows/sectors -> risk.

Only dated observations already validated elsewhere in the report are read
here. Nothing is scored, no gate or buy condition is touched, and a missing
input leaves its clause out (never 0 or an estimate). Reported background is
never written as a confirmed cause unless an article body was verified, and
even then the price contribution stays unconfirmed.
"""

from stock_lab_core.report_build import register_loaded_source
from stock_lab_core.report_evidence import number, records, stamp, text, first

register_loaded_source(__name__, __file__)

LABELS = {"^KS11": "코스피", "^KQ11": "코스닥", "^GSPC": "S&P500", "^IXIC": "나스닥",
          "^DJI": "다우", "^SOX": "필라델피아 반도체", "SOXX": "미국 반도체"}
INDICES = {"KR": ("^KS11", "^KQ11"), "US": ("^IXIC", "^SOX", "^GSPC")}


def _pct(value):
    return f"{value * 100:+.2f}%"


def _eok(value):
    return f"{value:+,.0f}억원"


def _move_word(change, *, live=False):
    size = abs(change)
    if size < 0.003:
        return "보합권에 머물렀습니다" if not live else "보합권입니다"
    up = change > 0
    word = ("급등" if up else "급락") if size >= 0.03 else ("상승" if up else "하락")
    if size < 0.01:
        word = "소폭 " + word
    return word + ("했습니다" if not live else " 중입니다")


def index_move(context, market, ticker, states, now):
    """Current move plus the comparison the reader needs: prior day, run, 5D."""
    from stock_lab_core.report_intraday import valid_live_observation
    state = (states or {}).get(market) or {}
    live = state.get("phase") == "intraday"
    closes = context.get("prices", {})
    closed = closes.get(ticker, {})
    if live:
        row = context.get("intraday_prices", {}).get(ticker, {})
        target = state.get("active_date")
        checked = max(now, stamp(context.get("quote_checked_at")) or now)
        if not target or row.get("date") != target or not valid_live_observation(row, market, checked, states=states):
            return None
        change = number(row.get("return"))
        # The last confirmed close is the prior session for a live quote.
        prior = number(closed.get("return")) if closed.get("date") and closed.get("date") < target else None
        last_down = number(closed.get("down_days")) or 0 if prior is not None else 0
        last_up = number(closed.get("up_days")) or 0 if prior is not None else 0
        down = (last_down + 1) if change is not None and change < 0 else 0
        up = (last_up + 1) if change is not None and change > 0 else 0
        prior_down = last_down if up == 1 else 0
        recent = None
        basis = "장중·미확정"
        if row.get("as_of"):
            from stock_lab_core.report_presentation import kst_time
            basis += "; " + kst_time(row["as_of"])
        date = target
    else:
        target = context.get("sessions", {}).get(market)
        if not target or closed.get("date") != target or closed.get("stale"):
            return None
        change = number(closed.get("return"))
        prior = number(closed.get("previous_return"))
        down = int(number(closed.get("down_days")) or 0)
        up = int(number(closed.get("up_days")) or 0)
        prior_down = int(number(closed.get("prior_down_days")) or 0)
        recent = number(closed.get("return_5d"))
        basis = "확정 종가"
        date = target
    if change is None:
        return None
    return dict(ticker=ticker, label=LABELS.get(ticker, ticker), market=market, change=change, prior=prior,
                down=int(down), up=int(up), prior_down=int(prior_down), recent=recent, live=live,
                date=date, basis=basis)


def _moves(context, states, now):
    moves = {}
    for market, tickers in INDICES.items():
        found = [move for ticker in tickers if (move := index_move(context, market, ticker, states, now))]
        if market == "US" and not any(m["ticker"] == "^SOX" for m in found):
            soxx = index_move(context, "US", "SOXX", states, now)
            if soxx:
                found.append(soxx)
        moves[market] = found
    return moves


def _josa(word, with_final, without_final):
    """Korean particle by the last syllable's final consonant (digits/latin: by reading)."""
    last = word.rstrip(")")[-1:]
    if "가" <= last <= "힣":
        return with_final if (ord(last) - 0xAC00) % 28 else without_final
    return with_final if last in "013678LMNR" else without_final


def _reversal(move):
    change, prior = move["change"], move["prior"]
    if prior is not None and change * prior < 0 and abs(prior) >= 0.01:
        if move["live"]:
            return f"전 거래일 {_pct(prior)}와 반대 방향입니다"
        if change > 0:
            fall = "급락" if prior <= -0.03 else "하락"
            return f"전 거래일 {_pct(prior)} {fall}을 {'하루 만에 되돌렸습니다' if change >= -prior else '일부 되돌렸습니다'}"
        return f"전 거래일 {_pct(prior)} 상승분을 {'모두 반납했습니다' if -change >= prior else '일부 반납했습니다'}"
    if change < 0 and move["down"] >= 2:
        return f"{move['down']}거래일째 하락{' 중입니다' if move['live'] else '했습니다'}"
    if change > 0 and move["up"] == 1 and move["prior_down"] >= 2:
        return f"{move['prior_down']}거래일 연속 하락을 {'끊는 흐름입니다' if move['live'] else '끊었습니다'}"
    if change > 0 and move["up"] >= 3:
        return f"{move['up']}거래일째 상승{' 중입니다' if move['live'] else '했습니다'}"
    return ""


def _lead_sentence(moves, order):
    """① The single most important change, the reader's session first."""
    lead_market = next((market for market in order if moves.get(market)), None)
    if not lead_market:
        return "", None
    lead = moves[lead_market][0]
    subject = lead["label"] + _josa(lead["label"], "이", "가")
    word = _move_word(lead["change"], live=lead["live"])
    reversal = _reversal(lead)
    stamp_ = f"({lead['date']} {lead['basis']})"
    if reversal and not lead["live"] and word.endswith("했습니다"):
        sentence = f"{subject} {_pct(lead['change'])} {word[:-4]}해 {reversal}{stamp_}."
    elif reversal:
        sentence = f"{subject} {_pct(lead['change'])} {word}{stamp_}. {reversal}."
    else:
        sentence = f"{subject} {_pct(lead['change'])} {word}{stamp_}."
    other = next((market for market in order if market != lead_market and moves.get(market)), None)
    if other:
        picks = moves[other][:2]
        same = all(m["change"] * lead["change"] > 0 for m in picks)
        opposite = all(m["change"] * lead["change"] < 0 for m in picks)
        if max(abs(m["change"]) for m in picks) >= 0.01 or not same:
            joined = ", ".join(f"{m['label']} {_pct(m['change'])}" for m in picks)
            rebound = all(m["prior"] is not None and m["prior"] <= -0.01 and m["change"] >= 0.03 for m in picks)
            verb = "급반등했습니다" if rebound else _move_word(sum(m["change"] for m in picks) / len(picks), live=picks[0]["live"])
            when = "앞선 미국장" if other == "US" else "한국장"
            if not same and not opposite:
                verb = "혼조였습니다"
            particle = "도" if same else "은 반대로" if opposite else "은"
            sentence += f" {when}{particle} {joined}로 {verb}({picks[0]['date']} {picks[0]['basis']})."
    return sentence, lead


def _background_sentence(claims, body_markets, corroboration, order):
    """② Reported background at its confirmed level; never a confirmed cause from a title."""
    parts = []
    for market in order:
        topics = [topic for topic in claims.get(market) or [] if topic]
        name = "한국" if market == "KR" else "미국"
        joined = "·".join(dict.fromkeys(topics[:2]))
        if market in body_markets:
            about = f"{joined} 관련 " if joined else ""
            parts.append(f"{name}장은 {about}기사 본문이 확인된 보도가 있습니다(내용은 시장 스토리, 가격 기여도 미확정)")
            continue
        if not topics:
            continue
        outlets = corroboration.get(market) or []
        count = f"{len(outlets)}개 매체 제목 일치, " if len(outlets) >= 2 else ""
        parts.append(f"{name}장 배경으로는 {joined}{_josa(joined, '이', '가')} 제목 기준으로 보도됐지만({count}본문 미확인) 원인으로 확정하지 않습니다")
    if not parts:
        return "같은 세션의 출처·시각 기준을 통과한 배경 보도가 없어 원인은 비워 둡니다."
    return ". ".join(parts) + "."


def _flow_turns(context, session_date):
    """Investor turns from validated public flows; today vs the completed-day history."""
    from stock_lab_core.public_market_data import validated_investor_flows
    today = validated_investor_flows(context.get("public_market_evidence"), session_date=session_date,
                                     checked_at=context.get("market_evidence_checked_at"))
    history = []
    if "public_flow_backfill" in context:
        from stock_lab_core.public_flow_backfill import summarize_backfill
        history, _ = summarize_backfill(context["public_flow_backfill"], checked_at=context.get("market_evidence_checked_at"))
    turns = {}
    for row in history:
        key = (row["market"], row["label"])
        days, direction = row.get("streak_days"), row.get("streak_direction")
        if not days or direction not in {"buy", "sell"}:
            continue
        if row.get("asof") == session_date:
            # History already holds today: a 1-day run is today's turn.
            prior = row.get("prior_streak_days")
            if days == 1 and prior:
                turns[key] = dict(direction=direction, prior_days=prior, sum_5=row.get("sum_5"))
            else:
                turns[key] = dict(direction=direction, run_days=days, sum_5=row.get("sum_5"))
        elif row.get("asof") and row["asof"] < session_date:
            value = next((t["value"] for t in today if (t["market"], t["label"]) == key), None)
            if value is not None and value != 0 and (value > 0) != (direction == "buy"):
                turns[key] = dict(direction="buy" if value > 0 else "sell", prior_days=days, sum_5=None)
            elif value is not None and value != 0:
                turns[key] = dict(direction=direction, run_days=days + 1, sum_5=None)
    return today, turns


def _flow_sentence(context, kr_date, sectors_kr, us_sectors):
    """③ Flows and strong/weak sectors, numbers attached."""
    parts, changes = [], []
    today, turns = _flow_turns(context, kr_date) if kr_date else ([], {})
    kospi = {row["label"]: row["value"] for row in today if row["market"] == "KOSPI"}
    if kospi:
        buys = [f"{label} {_eok(value)}" for label, value in kospi.items() if value > 0]
        sells = [f"{label} {_eok(value)}" for label, value in kospi.items() if value < 0]
        flow = "KOSPI 잠정 수급은 " + " / ".join(filter(None, [
            "·".join(buys) + " 순매수" if buys else "", "·".join(sells) + " 순매도" if sells else ""]))
        turn_bits = []
        for label in ("외국인", "기관"):
            turn = turns.get(("KOSPI", label))
            if turn and turn.get("prior_days"):
                was = "순매도" if turn["direction"] == "buy" else "순매수"
                now_ = "순매수" if turn["direction"] == "buy" else "순매도"
                turn_bits.append(f"{label}은 직전 {turn['prior_days']}거래일 {was}에서 {now_}로 돌아섰습니다")
                changes.append(f"{label}(KOSPI) {was} {turn['prior_days']}거래일 → {now_} 전환")
        parts.append(flow + (", " + "·".join(turn_bits) if turn_bits else ""))
    if sectors_kr:
        parts.append(sectors_kr)
    if us_sectors:
        high, low, rising, total, falling = us_sectors
        top, bottom = f"{high[1]}({high[2]}) {_pct(high[0])}", f"{low[1]}({low[2]}) {_pct(low[0])}"
        spread = (f"미국은 관측 업종 {total}개가 모두 올라 {top}가 가장 강했고 {bottom}가 가장 약했습니다" if rising == total else
                  f"미국은 관측 업종 {total}개가 모두 내려 {top}가 가장 덜 내렸고 {bottom}가 가장 많이 내렸습니다" if falling == total else
                  f"미국은 관측 업종 {total}개 중 {rising}개가 올라 {top}가 상위, {bottom}가 하위였습니다")
        parts.append(spread)
    return (". ".join(parts) + ".") if parts else "", changes, turns


def _risk_sentence(lead, moves, burden_rows, medium, turns, order):
    """④ What remains, with today's numbers, and what to check next."""
    risks = []
    if lead and lead["change"] > 0 and lead.get("recent") is not None and lead["recent"] < 0:
        risks.append(f"{lead['label']} 5거래일 수익률 {_pct(lead['recent'])}")
    foreign = turns.get(("KOSPI", "외국인")) or {}
    if foreign.get("direction") == "buy" and foreign.get("sum_5") is not None and foreign["sum_5"] < 0:
        risks.append(f"외국인 5거래일 누적 {_eok(foreign['sum_5'])}(여전히 순매도)")
    if lead and lead["change"] > 0 and medium:
        symbol, change = medium
        risks.append(f"{'반도체' if symbol in {'SMH', 'SOXX'} else '소프트웨어' if symbol == 'IGV' else symbol}({symbol}) 3개월 {_pct(change)}의 중기 하락권")
    if burden_rows:
        units = {"10Y 금리": "%", "VIX": "", "MOVE": "", "유가": "달러", "환율": "원"}
        risks.append("·".join(
            f"{row['name']} {row['value']:,.2f}{units.get(row['name'], '')}({row['state']})" for row in burden_rows[:2]))
    checks = []
    up = lead is not None and lead["change"] > 0
    if lead is None:
        checks.append("다음 확정 종가의 지수 방향")
    elif up:
        if foreign.get("direction") == "buy":
            checks.append("외국인 순매수가 다음 거래일에도 이어지는지")
        if any(m["ticker"] in {"^SOX", "SOXX"} and m["change"] > 0.03 for m in moves.get("US", [])):
            checks.append("미국 반도체가 다음 종가에서 반등폭을 지키는지")
        checks.append("상승이 다른 업종으로 넓어지는지" if not checks else "")
    else:
        checks.append("하락이 다른 업종으로 번지는지")
        if foreign.get("direction") == "sell":
            checks.append("외국인 순매도가 이어지는지")
        if lead["change"] <= -0.03:
            checks.append("다음 거래일에 낙폭 일부라도 되돌리는지")
    checks = [c for c in checks if c]
    sentence = ""
    if risks:
        sentence += "남은 부담은 " + ", ".join(risks) + "입니다. "
    sentence += "다음 확인 조건은 " + "·".join(checks) + "입니다(종합 해석)."
    return sentence


def daily_changes(moves, flow_changes, order):
    """'오늘 달라진 점': only comparisons the dated observations can show."""
    changes = []
    for market in order:
        for move in moves.get(market, [])[:2]:
            change, prior = move["change"], move["prior"]
            if prior is not None and change * prior < 0 and max(abs(change), abs(prior)) >= 0.005:
                changes.append(f"{move['label']} 방향 전환: 전 거래일 {_pct(prior)} → {_pct(change)}({move['date']} {move['basis']})")
            elif change > 0 and move["up"] == 1 and move["prior_down"] >= 2:
                changes.append(f"{move['label']} {move['prior_down']}거래일 연속 하락 종료({_pct(change)}, {move['date']})")
            elif change < 0 and move["down"] >= 2:
                changes.append(f"{move['label']} {move['down']}거래일 연속 하락({_pct(change)}, {move['date']})")
    return changes + flow_changes


def daily_reading(context, states, now, *, claims, body_markets, corroboration, burden_rows, medium,
                  kr_sector_text="", us_sectors=None, korea_first=True):
    """Return the four-step interpretation and the '오늘 달라진 점' list."""
    order = ("KR", "US") if korea_first else ("US", "KR")
    moves = _moves(context, states, now)
    lead_text, lead = _lead_sentence(moves, order)
    kr_date = (moves.get("KR") or [{}])[0].get("date") or context.get("sessions", {}).get("KR")
    flow_text, flow_changes, turns = _flow_sentence(context, kr_date, kr_sector_text, us_sectors)
    pieces = [lead_text or "확정 종가·검증된 장중 지수가 없어 당일 방향은 판단하지 않습니다.",
              _background_sentence(claims, body_markets, corroboration, order),
              flow_text,
              _risk_sentence(lead, moves, burden_rows, medium, turns, order)]
    return {"interpretation": " ".join(piece for piece in pieces if piece),
            "changes": daily_changes(moves, flow_changes, order), "lead": lead}


def corroborating_outlets(topic, rows):
    """Distinct publishers whose same-session titles carry the same topic (title level only)."""
    from stock_lab_core.report_market_summary import _korean_positive_drivers
    from stock_lab_core.report_presentation import news_theme
    wanted = set(topic.split("·"))
    outlets = []
    for row in records(rows):
        title = text(row.get("title"))
        found = set("·".join(_korean_positive_drivers(title)).split("·")) | {news_theme(title)}
        publisher = text(first(row, "publisher", "source"))
        if publisher and wanted & found and publisher not in outlets:
            outlets.append(publisher)
    return outlets
