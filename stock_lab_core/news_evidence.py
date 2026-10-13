"""Price observation and dated news evidence; never infer proven causality."""

from datetime import datetime, timedelta, timezone
import math
from urllib.parse import urlparse


KST = timezone(timedelta(hours=9))


def build_price_news_evidence(items, change_pct=None, *, now=None):
    now = now or datetime.now(KST)
    try:
        change = float(change_pct)
    except (ValueError, TypeError):
        change = float("nan")
    observation = f"가격 등락 {change:+.2f}%" if math.isfinite(change) else "가격 등락 미확인"
    rows, seen = [], set()
    for item in items or []:
        if not isinstance(item, dict) or item.get("category") != "종목 직접":
            continue
        try:
            published = datetime.strptime(str(item.get("published", "")), "%Y-%m-%d %H:%M").replace(tzinfo=KST)
            link = str(item.get("link", ""))
            parsed = urlparse(link)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                continue
        except ValueError:
            continue
        title = str(item.get("title") or "").strip()
        if not title or title in seen or not now - timedelta(hours=48) <= published <= now + timedelta(minutes=5):
            continue
        seen.add(title)
        rows.append({"보도시각(KST)": published.strftime("%Y-%m-%d %H:%M"), "관련 보도": title,
                     "제목 기반 해석": item.get("reason") or "방향성 근거 부족",
                     "출처": item.get("publisher") or "미제공", "원문": link})
    rows.sort(key=lambda row: row["보도시각(KST)"], reverse=True)
    return {"observation": observation, "rows": rows[:3],
            "conclusion": "최근 48시간 직접 보도 후보입니다. 가격 변동과의 인과관계는 미확인입니다." if rows
            else "최근 48시간 직접 보도 근거가 부족하여 등락 원인을 확정하지 않습니다."}


def render_price_news_evidence(st, items, change_pct=None):
    import pandas as pd

    evidence = build_price_news_evidence(items, change_pct)
    st.markdown("**등락과 관련 보도**")
    st.caption(evidence["observation"] + " · " + evidence["conclusion"])
    if evidence["rows"]:
        st.dataframe(pd.DataFrame(evidence["rows"]), hide_index=True, width="stretch",
                     column_config={"원문": st.column_config.LinkColumn("원문")})
