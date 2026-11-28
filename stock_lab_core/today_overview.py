"""Read-only connections between existing Today results; no fetching or scoring."""
import re

import pandas as pd

from stock_lab_core.decision_brief import text
from stock_lab_core.execution_readiness import build_execution_readiness
from stock_lab_core.portfolio import portfolio_flow_ticker_key
from stock_lab_core.sector_candidate_association import sector_market_from_row


def action_columns(row):
    """Execution first, technical suggestion second; preserve original fields."""
    source = dict(row)
    ready = build_execution_readiness(source)
    return {
        "오늘 행동": ready["label"],
        "보류 사유": text(ready.get("reason"), "-"),
        "기술적 타점": text(source.get("🔥기술적 타점"), text(source.get("기술적타점"), "-")),
        "후보 품질": text(source.get("후보품질"), text(source.get("📌후보등급"), "-")),
        "R/R": source.get("R/R", source.get("RR값", "-")),
        "계산시각": text(source.get("계산시각"), "미확인"),
        "가격입력ID": text(source.get("가격입력ID"), "미확인"),
    }


def observed_sessions(frame):
    """Use supplied source days, not the render date; mixed dates stay unknown."""
    days = {"KR": set(), "US": set()}
    for row in frame.to_dict("records") if isinstance(frame, pd.DataFrame) else []:
        market = sector_market_from_row({"티커": row.get("티커")})
        key = {"한국": "KR", "미국": "US"}.get(market)
        date = pd.to_datetime(row.get("가격자료기준일"), errors="coerce")
        if key and pd.notna(date):
            days[key].add(date.date().isoformat())
    return {market: next(iter(values)) for market, values in days.items()} if all(len(values) == 1 for values in days.values()) else None


def overview_counts(frame, hard_mask=None):
    """Partition unique subjects; hard blocks are a subset, never an extra total."""
    if not isinstance(frame, pd.DataFrame) or frame.empty or "티커" not in frame:
        return {"전체": 0, "방어우선": 0, "데이터확인": 0, "실행가능": 0, "기타대기": 0, "하드차단": 0, "중복종목": 0}
    work = frame.copy()
    work["_key"] = work["티커"].map(portfolio_flow_ticker_key)
    work = work[work["_key"].ne("")]
    work["_gate"] = work.get("게이트상태", pd.Series("", index=work.index)).fillna("")
    states = work.groupby("_key")["_gate"].agg(lambda values: next(iter(set(values))) if len(set(values)) == 1 else "데이터확인")
    hard = pd.Series(False, index=work.index)
    if isinstance(hard_mask, pd.Series):
        hard = hard_mask.reindex(work.index, fill_value=False).fillna(False).astype(bool)
    else:
        # Same display subset as today_queue_display; never an added subject.
        code = work.get("판정코드", pd.Series("", index=work.index)).fillna("")
        label = work.get("🔥기술적 타점", pd.Series("", index=work.index)).fillna("")
        hard = (code.str.contains("HARD_BLOCK", regex=False) | label.str.contains("하드차단", regex=False)) & ~code.isin({"HARD_BLOCK_BOLLINGER_UPPER", "HARD_BLOCK_MFI_OVERHEAT"})
    known = {"방어우선", "데이터확인", "실행가능"}
    return {"전체": len(states), **{key: int(states.eq(key).sum()) for key in known},
            "기타대기": int((~states.isin(known)).sum()), "하드차단": work.loc[hard, "_key"].nunique(),
            "중복종목": int(work["_key"].value_counts().gt(1).sum())}


def classify_review_flags(frame):
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return pd.DataFrame()
    result = frame.drop(columns=["확인 구분"], errors="ignore").copy()
    def category(row):
        issue = text(row.get("문제"), "")
        if issue == "파킹자산 · 종목점검 제외":
            return "의도된 제외"
        if "자동 감지된 중복/충돌 없음" in issue:
            return "정상"
        if issue == "돈흐름 후보가 오늘점검에 없음":
            return "점검 대상 범위 차이"
        if (issue in {"돈흐름 강세와 실행 방어 동시 존재", "buyish 원판정이 실행 게이트에서 낮아짐"}
                and text(row.get("등급"), "") == "참고"):
            return "후보는 강하지만 실행은 보류"
        return "자료·매칭 확인 필요"
    result.insert(0, "확인 구분", [category(row) for row in result.to_dict("records")])
    return result


def sector_observation_rows(cards, summary):
    """Project existing ranked cards and exact named captures onto saved gates."""
    records = summary.to_dict("records") if isinstance(summary, pd.DataFrame) else []
    rows = []
    for card in cards or []:
        market = text(card.get("market", card.get("시장")), "미확인")
        reps = text(card.get("representatives", card.get("오늘 포착종목")), "-")
        names = list(dict.fromkeys(name.strip() for name in re.split(r"[,/|·]", reps) if name.strip() and name.strip() != "-"))
        canonical = lambda symbol: portfolio_flow_ticker_key(str(symbol).upper().replace("BRK-", "BRK."))
        matches = []
        market_checks = []
        for name in names:
            # IDs may only identify the named, visible capture, not hidden candidates.
            symbols = {canonical(link['ticker']) for link in card.get('representative_links', [])
                       if link.get('name') == name and link.get('ticker')}
            candidates = [item for item in records
                          if name == text(item.get('종목명'), '') or canonical(name) == canonical(item.get('티커', ''))
                          or (len(symbols) == 1 and canonical(item.get('티커', '')) in symbols)]
            aligned = [item for item in candidates if market in {sector_market_from_row({'티커': item.get('티커')}), '혼합'}]
            if len(aligned) == 1:
                item = aligned[0]
                matches.append(f"{name}: {action_columns(item)['오늘 행동']} · {text(item.get('게이트근거'))}")
                if item.get("시장만모의해제"):
                    market_checks.append(f"{name}: {item['시장만모의해제']} · {text(item.get('시장만모의해제_근거'))}")
                else:
                    market_checks.append(f"{name}: 미검증 · 원계산 모의 관찰 없음")
            elif candidates and not aligned:
                matches.append(f"{name}: 대표주 시장 불일치 · 연결 보류")
                market_checks.append(f"{name}: 미확인 · 시장 불일치")
            else:
                matches.append(f"{name}: " + ("중복 매칭 확인" if len(aligned) > 1 else "점검 대상 범위 차이·이름 매칭 확인"))
                market_checks.append(f"{name}: 미확인 · 유일한 원계산 연결 불가")
        total = card.get("total", card.get("종합", "-"))
        rows.append({"시장": market, "순위": card.get("rank", card.get("순위", "-")),
                     "섹터": card.get("title", card.get("섹터", "-")), "기존 점수": total,
                     "섹터 관찰": card.get("verdict", card.get("최종읽기", "-")),
                     "오늘 포착종목": reps,
                     "종목 실행 상태": " / ".join(matches) if matches else ("점검 대상 범위 차이·이름 매칭 확인" if names else "포착 종목 없음"),
                     "시장 차단만 해제": " / ".join(market_checks) if market_checks else "미검증 · 다른 제한 해소 여부 별도 확인"})
    return pd.DataFrame(rows)


def render_overview(st, summary, cards, flags, *, hard_mask=None):
    counts = overview_counts(summary, hard_mask)
    st.caption(f"고유 종목 {counts['전체']} = 방어우선 {counts['방어우선']} + 데이터확인 {counts['데이터확인']} "
               f"+ 실행가능 {counts['실행가능']} + 기타대기 {counts['기타대기']} · 하드차단 {counts['하드차단']}은 전체 안의 부분집합")
    if counts["중복종목"]:
        st.warning(f"동일 종목 결과 중복 {counts['중복종목']}개 · 서로 다른 게이트는 집계에서 데이터확인으로 표시")
    sectors = sector_observation_rows(cards, summary)
    st.markdown("**어디가 먼저 좋아지는가 · 기존 섹터 관찰**")
    if not sectors.empty:
        first = sectors.groupby("시장", sort=False).head(3)
        st.dataframe(first, hide_index=True, width="stretch")
        with st.expander("한국·미국·혼합 전체 순위와 포착 종목"):
            st.dataframe(sectors, hide_index=True, width="stretch")
    else:
        st.caption("저장된 섹터 계산 결과 없음 · 전체 점검을 자동으로 다시 실행하지 않습니다.")
    issues = classify_review_flags(flags)
    if not issues.empty:
        actionable = issues[issues["확인 구분"].eq("자료·매칭 확인 필요")]
        st.markdown(f"**실제 자료·매칭 확인 {len(actionable)}건**")
        if not actionable.empty:
            st.dataframe(actionable, hide_index=True, width="stretch")
        with st.expander("후보 보류·대상 범위·의도된 제외"):
            st.dataframe(issues[~issues["확인 구분"].eq("자료·매칭 확인 필요")], hide_index=True, width="stretch")
    st.caption("기존 점검·섹터 계산 결과 재사용 · 섹터 관찰은 개별 종목 실행 허가가 아닙니다.")


from stock_lab_core.report_build import register_loaded_source
register_loaded_source(__name__, __file__)
