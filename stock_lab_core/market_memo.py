"""Market memo parser for the Today Check tab.

The parser intentionally treats pasted market notes as unverified input.  It
extracts sector tone, source-check flags, and portfolio/watchlist links without
calling external services.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable


@dataclass(frozen=True)
class MemoCategoryRule:
    name: str
    keywords: tuple[str, ...]
    exposure_keywords: tuple[str, ...] = ()


MARKET_MEMO_CATEGORY_RULES: tuple[MemoCategoryRule, ...] = (
    MemoCategoryRule(
        "반도체/AI",
        (
            "반도체", "ai", "nvidia", "nvda", "micron", "mu", "hbm", "openai",
            "deepseek", "eml", "cw 레이저", "coherent", "marvell", "마벨",
            "soxl", "soxx", "smh", "sandisk", "sndk", "crdo", "alab",
        ),
        (
            "반도체", "ai", "semiconductor", "soxl", "soxx", "smh", "nvda",
            "mu", "mrvl", "sndk", "crdo", "alab", "tsm", "amd", "avgo",
            "asml", "amzn", "0167a0", "396500", "139260", "005930", "000660",
        ),
    ),
    MemoCategoryRule(
        "지정학",
        ("이란", "휴전", "평화", "양해각서", "대만", "필리핀", "미얀마", "우크라이나", "중동", "호르무즈"),
        ("방산", "defense", "uranium", "oil", "유가", "에너지"),
    ),
    MemoCategoryRule(
        "매크로",
        (
            "산업생산", "소매판매", "실업률", "고정자산", "rba", "boj",
            "기준금리", "인플레이션", "역레포", "인민은행", "pboC".lower(),
        ),
        ("macro", "금리", "채권", "tlt", "ief", "달러", "환율"),
    ),
    MemoCategoryRule(
        "에너지",
        ("에너지", "t1 energy", "pemex", "유가", "원유", "천연가스", "opec", "역레포"),
        ("energy", "oil", "gas", "xle", "에너지", "원유", "유가"),
    ),
    MemoCategoryRule(
        "우주/항공",
        ("spacex", "spcx", "우주", "항공", "스타링크", "위성", "레이저 링크"),
        ("space", "우주", "항공", "arkx", "ita", "spcx"),
    ),
    MemoCategoryRule(
        "소비/중국",
        ("알리바바", "baba", "홍콩", "중국", "소매판매", "소비", "위안"),
        ("china", "중국", "baba", "kweb", "fxi", "소비"),
    ),
    MemoCategoryRule(
        "외환/금리",
        ("달러", "엔", "위안", "국채", "10년물", "20년물", "30년물", "금리", "환율", "호주 달러"),
        ("금리", "채권", "달러", "환율", "tlt", "ief", "uup", "yen", "jpy"),
    ),
    MemoCategoryRule(
        "조선/해운",
        ("조선", "해운", "선주", "호르무즈", "해협", "운임"),
        ("조선", "해운", "ship", "shipping", "운임"),
    ),
    MemoCategoryRule(
        "철강/소재",
        ("철강", "소재", "탄소 국경", "cbam", "수출 비용"),
        ("철강", "소재", "steel", "materials", "xme", "xle"),
    ),
    MemoCategoryRule(
        "규제/정책",
        ("규제", "정책", "당국", "조사", "기준 맞춤", "eu 기준", "탄소 국경"),
        ("규제", "정책", "은행", "보험", "금융"),
    ),
)


TICKER_ALIAS_MAP: dict[str, tuple[str, ...]] = {
    "NVDA": ("NVDA", "NVIDIA", "엔비디아"),
    "MU": ("MU", "MICRON", "마이크론"),
    "MRVL": ("MRVL", "MARVELL", "마벨"),
    "SNDK": ("SNDK", "SANDISK", "샌디스크"),
    "CRDO": ("CRDO", "CREDO", "크레도"),
    "ALAB": ("ALAB", "ASTERA", "아스테라"),
    "SOXL": ("SOXL",),
    "SOXX": ("SOXX",),
    "SMH": ("SMH",),
    "AMD": ("AMD",),
    "AVGO": ("AVGO", "BROADCOM", "브로드컴"),
    "TSM": ("TSM", "TSMC"),
    "ASML": ("ASML",),
    "AMAT": ("AMAT", "APPLIED MATERIALS"),
    "LRCX": ("LRCX", "LAM RESEARCH"),
    "KLAC": ("KLAC", "KLA"),
    "COHR": ("COHR", "COHERENT", "코히런트"),
    "LITE": ("LITE", "LUMENTUM", "루멘텀"),
    "BABA": ("BABA", "ALIBABA", "알리바바"),
    "TE": ("TE", "T1 ENERGY"),
    "SPCX": ("SPCX", "SPACEX", "SPACE X", "스페이스X"),
    "0167A0.KS": ("0167A0", "SOL AI 반도체", "SOL AI 반도체 TOP2"),
    "005930.KS": ("005930", "삼성전자"),
    "000660.KS": ("000660", "SK하이닉스", "하이닉스"),
}


POSITIVE_KEYWORDS = (
    "강세", "상승", "초과", "확보", "선점", "완료", "유지", "해소", "호재",
    "수요", "돌파", "환영", "개선", "확대", "장기 계약", "공급 계약",
)
NEGATIVE_KEYWORDS = (
    "하락", "감소", "미달", "약세", "사고", "조사", "비용 상승", "위험",
    "보류", "제한", "압력", "불확실", "악화", "버블", "인플레이션 고점",
    "이탈", "매도세", "급락", "추격 금지", "추격금지",
)
CAUTION_KEYWORDS = (
    "밈", "콜옵션", "yolo", "야간거래", "급증", "논의", "예정", "계획",
    "전자 서명", "ipo", "투자 라운드", "기업 가치", "채권 발행", "양해각서",
)
SOURCE_CHECK_KEYWORDS = (
    "밈", "콜옵션", "yolo", "야간거래", "전자 서명", "예정", "논의", "계획",
    "투자 라운드", "기업 가치", "ipo", "채권 발행", "비상장", "휴전",
)

LEVERAGED_TICKERS = {
    "TQQQ", "QLD", "SOXL", "TECL", "UPRO", "SSO", "FNGU", "BULZ",
    "NVDL", "TSLL", "USD", "423920.KS", "494310.KS",
}
GROWTH_ROTATION_TICKERS = {"QQQ", "XLK", "SOXX", "SMH", "SOXL", "TQQQ", "QLD"}
VALUE_DEFENSIVE_ROTATION_TICKERS = {"DIA", "XLI", "XLF", "XLP", "XLU"}
INDEX_ROTATION_TICKERS = GROWTH_ROTATION_TICKERS | VALUE_DEFENSIVE_ROTATION_TICKERS | {
    "VOO", "069500.KS", "229200.KS",
}


def _norm(text: object) -> str:
    return str(text or "").strip()


def _lower(text: object) -> str:
    return _norm(text).lower()


def _strip_memo_line(line: str) -> str:
    line = re.sub(r"^[\s>*•\-–—·]+", "", _norm(line))
    line = re.sub(r"^[^\w가-힣$%]+", "", line)
    return line.strip()


def split_market_memo_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw in _norm(text).splitlines():
        line = _strip_memo_line(raw)
        if not line:
            continue
        if set(line) <= {"━", "-", "─", " "}:
            continue
        if line in {"시황", "종목"}:
            continue
        if "양봉업자 뉴스픽" in line:
            continue
        lines.append(line)
    return lines


def _category_from_heading(line: str) -> str:
    low = _lower(line)
    for rule in MARKET_MEMO_CATEGORY_RULES:
        if rule.name.lower() in low:
            return rule.name
        if any(kw.lower() == low for kw in rule.keywords):
            return rule.name
    return ""


def categorize_market_memo_line(line: str, current_category: str = "") -> str:
    heading = _category_from_heading(line)
    if heading:
        return heading
    low = _lower(line)
    scores: dict[str, int] = {}
    for rule in MARKET_MEMO_CATEGORY_RULES:
        hit = sum(1 for kw in rule.keywords if kw and kw.lower() in low)
        if hit:
            scores[rule.name] = hit
    if scores:
        return max(scores, key=scores.get)
    return current_category or "기타"


def score_market_memo_line(line: str) -> tuple[int, list[str]]:
    low = _lower(line)
    pos = [kw for kw in POSITIVE_KEYWORDS if kw in low]
    neg = [kw for kw in NEGATIVE_KEYWORDS if kw in low]
    caution = [kw for kw in CAUTION_KEYWORDS if kw in low]
    score = len(pos) - len(neg)
    if caution and score > 1:
        score -= 1
    tags = []
    if pos:
        tags.append("호재")
    if neg:
        tags.append("악재")
    if caution:
        tags.append("과열/확인")
    return score, tags


def _tone_from_score(score: float, caution_count: int = 0) -> str:
    if score >= 2:
        return "호재 우위" if caution_count < 2 else "호재+과열"
    if score <= -2:
        return "악재 우위"
    if caution_count >= 2:
        return "확인 필요"
    if score > 0:
        return "소폭 호재"
    if score < 0:
        return "소폭 부담"
    return "혼조"


def _contains_alias(line: str, alias: str) -> bool:
    alias = _norm(alias)
    if not alias:
        return False
    low = _lower(line)
    alias_low = alias.lower()
    if re.fullmatch(r"[A-Za-z0-9.]{1,12}", alias):
        return re.search(rf"(?<![A-Za-z0-9]){re.escape(alias_low)}(?![A-Za-z0-9])", low) is not None
    return alias_low in low


def _mentioned_tickers(line: str, extra_aliases: dict[str, tuple[str, ...]] | None = None) -> list[str]:
    aliases: dict[str, tuple[str, ...]] = dict(TICKER_ALIAS_MAP)
    if extra_aliases:
        aliases.update(extra_aliases)
    found: list[str] = []
    for ticker, names in aliases.items():
        if any(_contains_alias(line, alias) for alias in names):
            found.append(ticker)
    return found


def _source_check_reason(line: str) -> str:
    low = _lower(line)
    reasons = []
    if any(kw in low for kw in ("밈", "콜옵션", "yolo", "야간거래", "급증")):
        reasons.append("수급/심리성 재료")
    if any(kw in low for kw in ("예정", "논의", "계획", "전자 서명", "양해각서", "휴전")):
        reasons.append("확정 전 이벤트")
    if any(kw in low for kw in ("openai", "deepseek", "spacex", "기업 가치", "투자 라운드", "ipo")):
        reasons.append("비상장/출처 확인 필요")
    if any(kw in low for kw in ("채권 발행", "기준금리", "국채", "인민은행", "rba", "boj")):
        reasons.append("매크로/금리 수치 확인")
    if re.search(r"(\d+\.?\d*)\s*(억|조|bp|%|달러|위안)", line):
        reasons.append("숫자 데이터 확인")
    return " · ".join(dict.fromkeys(reasons)) or "출처 확인 필요"


def _iter_table_rows(table, limit: int = 5) -> list[dict]:
    if table is None:
        return []
    try:
        if hasattr(table, "empty") and table.empty:
            return []
        if hasattr(table, "head") and hasattr(table, "iterrows"):
            return [row.to_dict() for _, row in table.head(limit).iterrows()]
    except Exception:
        return []
    if isinstance(table, dict):
        return [table]
    rows = []
    try:
        for item in list(table)[:limit]:
            rows.append(dict(item) if isinstance(item, dict) else {"value": item})
    except Exception:
        return []
    return rows


def _fmt_auto_pct(value) -> str:
    try:
        number = float(value)
    except Exception:
        return "-"
    if not (number == number):
        return "-"
    pct = number * 100
    return f"{pct:+.1f}%"


def _fmt_macro_chg_pct(value) -> str:
    try:
        number = float(value)
    except Exception:
        return "-"
    if not (number == number):
        return "-"
    return f"{number:+.1f}%"


def _fmt_auto_num(value, digits: int = 2) -> str:
    try:
        number = float(value)
    except Exception:
        return "-"
    if not (number == number):
        return "-"
    return f"{number:,.{digits}f}"


def _flow_row_label(row: dict) -> str:
    name = _norm(row.get("섹터") or row.get("테마") or row.get("하위테마") or row.get("ETF 이름") or row.get("종목명"))
    ticker = _norm(row.get("Ticker") or row.get("티커"))
    if name and ticker:
        return f"{name}({ticker})"
    return name or ticker or "-"


def _flow_value(row: dict, key: str, default: float = 0.0) -> float:
    try:
        value = float(row.get(key, default))
    except Exception:
        return default
    return value if value == value else default


def _flow_action_phrase(row: dict) -> str:
    state = _norm(row.get("상태") or row.get("테마판정"))
    ret_3m = _flow_value(row, "3개월수익률")
    accel = _flow_value(row, "가속도")
    score = _flow_value(row, "돈흐름점수", _flow_value(row, "테마돈흐름점수"))
    if "과열" in state or ret_3m >= 0.45 or accel >= 0.35:
        return "추격보다 눌림 확인"
    if "강세" in state or score >= 30:
        return "주도 흐름 유지"
    if accel < 0:
        return "상승은 있으나 탄력 둔화"
    if score <= 0:
        return "관찰 우선"
    return "선별 관찰"


def _flow_bullet(row: dict, score_col: str = "돈흐름점수") -> str:
    label = _flow_row_label(row)
    score = _fmt_auto_num(row.get(score_col), 1) if row.get(score_col) not in [None, ""] else "-"
    ret_3m = _fmt_auto_pct(row.get("3개월수익률"))
    accel = _fmt_auto_pct(row.get("가속도"))
    state = _norm(row.get("상태") or row.get("테마판정"))
    action = _flow_action_phrase(row)
    state_text = f", 상태 {state}" if state else ""
    return f"{label} 3M {ret_3m}, 가속도 {accel}, 돈흐름 {score}점{state_text} — {action}"


def _row_ticker(row: dict) -> str:
    return _norm(row.get("Ticker") or row.get("티커") or row.get("ticker")).upper()


def _is_leveraged_row(row: dict) -> bool:
    ticker = _row_ticker(row)
    text = " ".join(
        _lower(row.get(key, ""))
        for key in ("종목명", "자산명", "name", "ETF 이름", "asset_class", "source", "type")
    )
    if ticker in LEVERAGED_TICKERS:
        return True
    return any(
        token in text
        for token in ("leveraged", "ultrapro", "ultra qqq", "bull 3x", "3x", "2x", "레버리지", "레버")
    )


def _rotation_value(row: dict, *keys: str, default: float | None = None) -> float | None:
    for key in keys:
        if key in row and row.get(key) not in (None, ""):
            try:
                value = float(row.get(key))
            except Exception:
                continue
            if value == value:
                return value
    return default


def _rotation_label(row: dict) -> str:
    label = _norm(
        row.get("지수/스타일")
        or row.get("섹터")
        or row.get("테마")
        or row.get("ETF 이름")
        or row.get("종목명")
    )
    ticker = _row_ticker(row)
    if label and ticker:
        return f"{label}({ticker})"
    return label or ticker or "-"


def _mean_rotation(rows: list[dict], tickers: set[str], key: str) -> tuple[float | None, int]:
    values = [
        _rotation_value(row, key)
        for row in rows
        if _row_ticker(row) in tickers and _rotation_value(row, key) is not None
    ]
    if not values:
        return None, 0
    return sum(float(v) for v in values) / len(values), len(values)


def _collect_rotation_rows(index_rotation_rows=None, flow_snapshot: dict | None = None) -> list[dict]:
    rows = _iter_table_rows(index_rotation_rows, limit=80)
    if rows:
        return rows

    flow_snapshot = flow_snapshot if isinstance(flow_snapshot, dict) else {}
    collected: list[dict] = []
    seen: set[str] = set()
    for table_name in ("flow_df", "us_top5", "global_top"):
        for row in _iter_table_rows(flow_snapshot.get(table_name), limit=400):
            ticker = _row_ticker(row)
            if ticker not in INDEX_ROTATION_TICKERS or ticker in seen:
                continue
            seen.add(ticker)
            collected.append({
                "시장": _norm(row.get("구분")),
                "지수/스타일": _norm(row.get("섹터") or row.get("ETF 이름")),
                "Ticker": ticker,
                "2W": _rotation_value(row, "2주수익률"),
                "1M": _rotation_value(row, "1개월수익률"),
                "3M": _rotation_value(row, "3개월수익률"),
                "RS(3M)": _rotation_value(row, "RS_3m", "RS(3M)"),
                "돈흐름점수": _rotation_value(row, "돈흐름점수"),
                "상태": _norm(row.get("상태")),
                "판정": _norm(row.get("상태")),
            })
    return collected


def _rotation_labels(rows: list[dict], key: str, positive: bool, limit: int = 3) -> str:
    ranked = []
    for row in rows:
        value = _rotation_value(row, key)
        if value is None:
            continue
        if positive and value <= 0:
            continue
        if not positive and value >= 0:
            continue
        ranked.append((value, _rotation_label(row)))
    ranked.sort(key=lambda item: item[0], reverse=positive)
    return ", ".join(f"{label}({_fmt_auto_pct(value)})" for value, label in ranked[:limit])


def _build_rotation_context(index_rotation_rows=None, flow_snapshot: dict | None = None) -> dict:
    rows = _collect_rotation_rows(index_rotation_rows, flow_snapshot)
    if not rows:
        return {"has_data": False, "rows": []}

    short_key = ""
    growth_avg = None
    rotation_avg = None
    for key in ("1D", "5D", "2W", "1M"):
        growth, growth_count = _mean_rotation(rows, GROWTH_ROTATION_TICKERS, key)
        rotation, rotation_count = _mean_rotation(rows, VALUE_DEFENSIVE_ROTATION_TICKERS, key)
        if growth_count and rotation_count:
            short_key = key
            growth_avg = growth
            rotation_avg = rotation
            break

    rotation_detected = False
    growth_weak = False
    if short_key and growth_avg is not None and rotation_avg is not None:
        growth_weak = growth_avg < 0
        rotation_detected = (growth_avg < 0 <= rotation_avg) or ((rotation_avg - growth_avg) >= 0.012)

    semi_short_weak = False
    for row in rows:
        ticker = _row_ticker(row)
        if ticker not in {"SOXX", "SMH", "SOXL", "QQQ", "XLK", "TQQQ", "QLD"}:
            continue
        judgement = _norm(row.get("판정") or row.get("상태"))
        short_value = _rotation_value(row, short_key) if short_key else None
        if "단기 이탈" in judgement or "장기주도/단기이탈" in judgement or (short_value is not None and short_value < 0):
            semi_short_weak = True
            break

    return {
        "has_data": True,
        "rows": rows,
        "short_key": short_key,
        "growth_avg": growth_avg,
        "rotation_avg": rotation_avg,
        "growth_weak": growth_weak,
        "rotation_detected": rotation_detected,
        "semi_short_weak": semi_short_weak,
        "inflow": _rotation_labels(rows, short_key, True) if short_key else "",
        "outflow": _rotation_labels(rows, short_key, False) if short_key else "",
        "leaders_3m": _rotation_labels(rows, "3M", True),
    }


def _active_event_names(event_rows) -> list[str]:
    return [
        _norm(row.get("이벤트"))
        for row in _iter_table_rows(event_rows, limit=12)
        if _norm(row.get("상태")) in {"임박", "당일", "잔여"} and _norm(row.get("이벤트"))
    ]


def _weekday_kr(dt: datetime) -> str:
    return ("월", "화", "수", "목", "금", "토", "일")[dt.weekday()]


def _format_auto_memo_time(now: datetime | None = None) -> str:
    dt = now or datetime.now()
    hour = dt.hour
    ampm = "오전" if hour < 12 else "오후"
    display_hour = hour if 1 <= hour <= 12 else (hour - 12 if hour > 12 else 12)
    return f"{dt.month}/{dt.day} ({_weekday_kr(dt)}) · {ampm} {display_hour}시"


def _macro_bullets(macro_data: dict | None) -> list[str]:
    bullets = []
    if not isinstance(macro_data, dict):
        return bullets
    for name in ("10Y 금리", "환율", "VIX", "MOVE", "유가"):
        info = macro_data.get(name)
        if not isinstance(info, dict):
            continue
        val = _fmt_auto_num(info.get("val"), 2)
        chg = _fmt_macro_chg_pct(info.get("chg"))
        icon = _norm(info.get("icon"))
        storm = bool(info.get("storm", False))
        note = "경고권" if storm else ("상승" if icon == "🔺" else ("하락" if icon == "🔻" else "중립"))
        bullets.append(f"{name} {val}, 1개월 {chg}, 방향 {note}")
    return bullets


def _event_bullets(event_rows) -> list[str]:
    bullets = []
    for row in _iter_table_rows(event_rows, limit=8):
        state = _norm(row.get("상태"))
        if state not in {"임박", "당일", "잔여"}:
            continue
        event = _norm(row.get("이벤트"))
        dday = _norm(row.get("D-Day"))
        impact = _norm(row.get("영향") or row.get("해석"))
        market = _norm(row.get("시장"))
        if event:
            suffix = f", {impact}" if impact else ""
            bullets.append(f"{event} {dday}({state}) · {market}{suffix}")
    return bullets[:5]


def _summary_bullets(summary_rows) -> list[str]:
    bullets = []
    rows = _iter_table_rows(summary_rows, limit=80)
    buyish = []
    leveraged_watch = []
    caution = []
    hard = []
    for row in rows:
        name = _norm(row.get("종목명") or row.get("자산명"))
        ticker = _norm(row.get("티커"))
        label = _norm(row.get("🔥기술적 타점") or row.get("판정분류"))
        code = _norm(row.get("판정코드"))
        item = f"{name or ticker}({ticker})" if ticker else (name or "-")
        if "HARD_BLOCK" in code or "하드차단" in label:
            hard.append(item)
        elif any(word in label for word in ("매수", "진입", "DCA", "적립", "탑승", "눌림")):
            if _is_leveraged_row(row):
                leveraged_watch.append(item)
            else:
                buyish.append(item)
        elif any(word in label for word in ("주의", "차단", "과열", "보류", "관망")):
            caution.append(item)
    if buyish:
        bullets.append("매수/관심 후보: " + ", ".join(buyish[:5]))
    if leveraged_watch:
        bullets.append("레버리지 관찰 후보(추격 제외): " + ", ".join(leveraged_watch[:5]))
    if caution:
        bullets.append("주의/차단 후보: " + ", ".join(caution[:5]))
    if hard:
        bullets.append("하드차단 우선 확인: " + ", ".join(hard[:5]))
    return bullets


def _news_bullets(news_rows) -> list[str]:
    bullets = []
    for row in _iter_table_rows(news_rows, limit=20):
        title = _norm(row.get("title") or row.get("제목"))
        if not title:
            continue
        ticker = _norm(row.get("ticker") or row.get("티커"))
        name = _norm(row.get("name") or row.get("종목명"))
        sentiment = _norm(row.get("sentiment") or row.get("감성"))
        publisher = _norm(row.get("publisher") or row.get("출처"))
        subject = name or ticker
        prefix = f"{subject}: " if subject else ""
        tail_parts = [x for x in (sentiment, publisher) if x]
        tail = f" ({', '.join(tail_parts)})" if tail_parts else ""
        bullets.append(f"{prefix}{title}{tail}")
    return bullets


def _market_news_bullets(news_rows) -> list[str]:
    bullets = []
    for row in _iter_table_rows(news_rows, limit=30):
        title = _norm(row.get("title") or row.get("제목"))
        if not title:
            continue
        category = _norm(row.get("market_category") or row.get("category") or "시장")
        publisher = _norm(row.get("publisher") or row.get("source") or row.get("출처"))
        published = _norm(row.get("published"))
        meta = " · ".join(x for x in (publisher, published) if x)
        tail = f" ({meta})" if meta else ""
        bullets.append(f"[{category}] {title}{tail}")
    return bullets


def _auto_insight_bullets(
    flow_snapshot,
    macro_data,
    event_rows,
    news_rows,
    summary_rows,
    market_news_rows=None,
    index_rotation_rows=None,
) -> list[str]:
    bullets: list[str] = []
    flow_snapshot = flow_snapshot if isinstance(flow_snapshot, dict) else {}
    rotation_ctx = _build_rotation_context(index_rotation_rows, flow_snapshot)
    flow_df = flow_snapshot.get("flow_df")
    flow_rows = _iter_table_rows(flow_df, limit=250)
    semi_rows = [
        row for row in flow_rows
        if any(
            key in " ".join(_lower(row.get(k, "")) for k in ("섹터", "Ticker", "ETF 이름"))
            for key in ("반도체", "semiconductor", "soxx", "soxl", "smh", "0167a0")
        )
    ]
    if semi_rows:
        top = sorted(semi_rows, key=lambda r: _flow_value(r, "돈흐름점수"), reverse=True)[0]
        overheated = sum(
            1 for row in semi_rows
            if "과열" in _norm(row.get("상태")) or _flow_value(row, "3개월수익률") >= 0.45
        )
        if overheated >= 2:
            if rotation_ctx.get("semi_short_weak"):
                short_key = rotation_ctx.get("short_key") or "단기"
                bullets.append(
                    f"반도체/AI는 {_flow_row_label(top)} 중심의 중기 돈흐름은 강하지만 {short_key} 기준 단기 이탈이 있어, 호재 우위보다 눌림/종가 확인이 우선입니다."
                )
            else:
                bullets.append(
                    f"반도체/AI는 {_flow_row_label(top)} 중심으로 중기 돈흐름이 강하지만 과열 표식이 많아 추격보다 눌림 확인이 우선입니다."
                )
        else:
            bullets.append(
                f"반도체/AI는 {_flow_row_label(top)} 중심으로 중기 주도 흐름이 유지됩니다. 후보는 정밀관측소 타점과 같이 봅니다."
            )

    if rotation_ctx.get("rotation_detected"):
        short_key = rotation_ctx.get("short_key") or "단기"
        growth_avg = rotation_ctx.get("growth_avg")
        rotation_avg = rotation_ctx.get("rotation_avg")
        spread_text = ""
        if growth_avg is not None and rotation_avg is not None:
            spread_text = f" 성장주 {_fmt_auto_pct(growth_avg)} vs 다우·산업재·방어 {_fmt_auto_pct(rotation_avg)}."
        flow_text = []
        if rotation_ctx.get("inflow"):
            flow_text.append(f"유입: {rotation_ctx['inflow']}")
        if rotation_ctx.get("outflow"):
            flow_text.append(f"이탈: {rotation_ctx['outflow']}")
        suffix = " / ".join(flow_text)
        bullets.append(
            f"{short_key} 기준 단기 자금은 나스닥·기술·반도체보다 다우·산업재·금융·방어 쪽이 상대적으로 강합니다.{spread_text}"
            + (f" {suffix}" if suffix else "")
        )
    elif rotation_ctx.get("growth_weak"):
        short_key = rotation_ctx.get("short_key") or "단기"
        bullets.append(
            f"{short_key} 기준 성장주/반도체가 약해진 구간입니다. 중기 주도 섹터라도 신규 추격보다 지지 확인이 우선입니다."
        )

    top_tables = [
        flow_snapshot.get("us_top5"),
        flow_snapshot.get("kr_top5"),
        flow_snapshot.get("theme_top5"),
    ]
    leaders = []
    for table in top_tables:
        rows = _iter_table_rows(table, limit=1)
        if rows:
            leaders.append(_flow_row_label(rows[0]))
    if leaders:
        bullets.append("중기 돈흐름 상위 축은 " + ", ".join(dict.fromkeys(leaders[:4])) + "입니다.")

    if isinstance(macro_data, dict) and macro_data:
        relief = []
        pressure = []
        for name, info in macro_data.items():
            if not isinstance(info, dict):
                continue
            icon = _norm(info.get("icon"))
            storm = bool(info.get("storm", False))
            if storm:
                pressure.append(name)
            elif name in {"10Y 금리", "VIX", "MOVE", "유가"} and icon == "🔻":
                relief.append(name)
            elif name in {"환율", "10Y 금리", "VIX"} and icon == "🔺":
                pressure.append(name)
        if relief or pressure:
            text = []
            if relief:
                text.append(f"완화: {', '.join(relief[:3])}")
            if pressure:
                text.append(f"부담: {', '.join(pressure[:3])}")
            bullets.append("매크로는 " + " / ".join(text) + " 흐름입니다.")

    events = _active_event_names(event_rows)
    if events:
        bullets.append("이벤트 리스크는 " + ", ".join(events[:3]) + " 일정 때문에 장중 변동성을 키울 수 있습니다.")
        if any("fomc" in _lower(event) for event in events):
            bullets.append("FOMC 전후에는 QQQ/TQQQ/QLD/SOXL 같은 성장주·레버리지 추격보다 금리 반응과 종가 확인이 우선입니다.")

    portfolio_lines = _summary_bullets(summary_rows)
    if portfolio_lines:
        bullets.append("내 포트 기준으로는 " + " / ".join(portfolio_lines[:2]) + "를 먼저 확인합니다.")

    news_count = len(_news_bullets(news_rows))
    if news_count:
        bullets.append(f"종목 뉴스는 {news_count}건을 수집했지만 RSS 제목 기준이므로 원문 확인 후 재료 강도를 판단합니다.")

    market_news_count = len(_market_news_bullets(market_news_rows))
    if market_news_count:
        bullets.append(f"시장 뉴스/서사 {market_news_count}건을 수집했습니다. 돈흐름과 같은 방향인지 확인하세요.")

    if not bullets:
        bullets.append("자동 수집 데이터가 제한적입니다. 돈흐름보다 직접 붙여넣은 뉴스/시황을 함께 확인하세요.")
    return bullets[:8]


def build_auto_market_memo(
    flow_snapshot: dict | None = None,
    macro_data: dict | None = None,
    event_rows=None,
    index_rotation_rows=None,
    market_news_rows=None,
    news_rows=None,
    summary_rows=None,
    now: datetime | None = None,
) -> str:
    """Build a paste-ready market memo from existing app data.

    This produces a deterministic draft; it does not verify external facts
    beyond the data already collected by the app.
    """
    flow_snapshot = flow_snapshot if isinstance(flow_snapshot, dict) else {}
    lines = [
        "🌇 Stock Lab 자동 뉴스픽",
        _format_auto_memo_time(now),
        "━━━━━━━━━━━━",
        "📊  시 황",
        "━━━━━━━━━━━━",
        "",
    ]

    insight_lines = _auto_insight_bullets(
        flow_snapshot,
        macro_data,
        event_rows,
        news_rows,
        summary_rows,
        market_news_rows,
        index_rotation_rows,
    )
    if insight_lines:
        lines.append("🧠 핵심 해석")
        for item in insight_lines:
            lines.append(f"• {item}")
        lines.append("")

    semis = []
    flow_df = flow_snapshot.get("flow_df")
    for row in _iter_table_rows(flow_df, limit=200):
        joined = " ".join(_lower(row.get(k, "")) for k in ("섹터", "Ticker", "ETF 이름"))
        if any(key in joined for key in ("반도체", "semiconductor", "soxx", "soxl", "smh", "0167a0")):
            semis.append(row)
    if semis:
        lines.append("🖥 반도체·AI")
        for row in sorted(semis, key=lambda r: _flow_value(r, "돈흐름점수", -999.0), reverse=True)[:3]:
            lines.append(f"• {_flow_bullet(row)}")
        lines.append("")

    flow_sections = [
        ("🌊 돈흐름", "미국 섹터", flow_snapshot.get("us_top5"), "돈흐름점수", 3),
        ("🇰🇷 국내 섹터", "한국 섹터", flow_snapshot.get("kr_top5"), "돈흐름점수", 3),
        ("🌐 글로벌/ETF", "글로벌", flow_snapshot.get("global_top"), "돈흐름점수", 2),
        ("🧩 테마", "테마", flow_snapshot.get("theme_top5"), "테마돈흐름점수", 3),
    ]
    used_header = set()
    for header, _, table, score_col, limit in flow_sections:
        rows = _iter_table_rows(table, limit=limit)
        if not rows:
            continue
        if header not in used_header:
            lines.append(header)
            used_header.add(header)
        for row in rows:
            lines.append(f"• {_flow_bullet(row, score_col=score_col)}")
        lines.append("")

    rotation_ctx = _build_rotation_context(index_rotation_rows, flow_snapshot)
    rotation_rows = rotation_ctx.get("rows", [])
    if rotation_rows and rotation_ctx.get("short_key"):
        short_key = rotation_ctx["short_key"]
        lines.append("🧭 지수/스타일 로테이션")
        if rotation_ctx.get("rotation_detected"):
            lines.append(
                f"• {short_key} 기준 성장주보다 다우·산업재·금융·방어가 강합니다 — "
                f"성장주 {_fmt_auto_pct(rotation_ctx.get('growth_avg'))}, "
                f"다우·방어 {_fmt_auto_pct(rotation_ctx.get('rotation_avg'))}"
            )
        if rotation_ctx.get("inflow"):
            lines.append(f"• 단기 유입: {rotation_ctx['inflow']}")
        if rotation_ctx.get("outflow"):
            lines.append(f"• 단기 이탈: {rotation_ctx['outflow']}")
        if rotation_ctx.get("leaders_3m"):
            lines.append(f"• 3M 중기 주도: {rotation_ctx['leaders_3m']}")
        lines.append("")

    macro_lines = _macro_bullets(macro_data)
    event_lines = _event_bullets(event_rows)
    if macro_lines or event_lines:
        lines.append("📉 매크로·이벤트")
        for item in macro_lines[:5]:
            lines.append(f"• {item}")
        for item in event_lines:
            lines.append(f"• {item}")
        lines.append("")

    market_news_lines = _market_news_bullets(market_news_rows)
    if market_news_lines:
        lines.append("📰 시장 뉴스/서사")
        for item in market_news_lines[:15]:
            lines.append(f"• {item}")
        lines.append("")

    portfolio_lines = _summary_bullets(summary_rows)
    if portfolio_lines:
        lines.append("🧭 오늘점검")
        for item in portfolio_lines:
            lines.append(f"• {item}")
        lines.append("")

    news_lines = _news_bullets(news_rows)
    if news_lines:
        lines.append("━━━━━━━━━━━━")
        lines.append("🎯  종 목")
        lines.append("━━━━━━━━━━━━")
        lines.append("")
        for item in news_lines[:12]:
            lines.append(f"• {item}")
        lines.append("")

    lines.append("※ 자동 생성 초안입니다. RSS/시장 데이터 수집 시점과 원문 출처를 확인한 뒤 판단하세요.")
    return "\n".join(lines).strip()


def _build_extra_aliases(universe: Iterable[dict] | None) -> dict[str, tuple[str, ...]]:
    aliases: dict[str, tuple[str, ...]] = {}
    for item in universe or []:
        ticker = _norm(item.get("ticker", "")).upper()
        name = _norm(item.get("name", ""))
        if not ticker:
            continue
        base = re.sub(r"\.(KS|KQ)$", "", ticker, flags=re.IGNORECASE)
        item_aliases = [ticker, base]
        if name:
            item_aliases.append(name)
        aliases[ticker] = tuple(dict.fromkeys(a for a in item_aliases if a))
    return aliases


def infer_market_memo_exposures(item: dict) -> list[str]:
    text = " ".join(
        _lower(item.get(key, ""))
        for key in ("ticker", "name", "asset_class", "source", "type")
    )
    exposures: list[str] = []
    for rule in MARKET_MEMO_CATEGORY_RULES:
        if any(kw.lower() in text for kw in rule.exposure_keywords):
            exposures.append(rule.name)
    return exposures


def _action_for_link(score: float, tone: str, explicit: bool) -> str:
    if score >= 2 and "과열" in tone:
        return "관심 강화 · 추격 금지 · 눌림 확인"
    if score >= 2:
        return "정밀관측 우선 · 분할 후보"
    if score <= -2:
        return "리스크 점검 · 신규매수 보수"
    if "확인" in tone:
        return "출처 확인 후 판단"
    return "방향성 확인"


def _headline_risk_context(lines: list[str]) -> dict:
    text = " ".join(_lower(line) for line in lines)
    rotation_caution = any(
        token in text
        for token in (
            "단기 이탈", "장기주도/단기이탈", "로테이션", "다우", "산업재",
            "방어", "매도세", "추격 금지", "추격금지", "종가 확인", "눌림/종가",
        )
    )
    event_caution = any(token in text for token in ("fomc", "금리 반응", "장중 변동성", "이벤트 리스크"))
    leveraged_caution = any(token in text for token in ("tqqq", "qld", "soxl", "레버리지"))
    return {
        "rotation": rotation_caution,
        "event": event_caution,
        "leverage": leveraged_caution,
        "any": rotation_caution or event_caution or leveraged_caution,
    }


def analyze_market_memo(text: str, universe: Iterable[dict] | None = None) -> dict:
    lines = split_market_memo_lines(text)
    extra_aliases = _build_extra_aliases(universe)
    current_category = ""
    line_items: list[dict] = []
    category_stats: dict[str, dict] = defaultdict(lambda: {"score": 0, "count": 0, "caution": 0, "examples": []})
    ticker_stats: dict[str, dict] = defaultdict(lambda: {"score": 0, "count": 0, "categories": set(), "examples": [], "caution": 0})
    verification_flags: list[dict] = []

    for line in lines:
        heading = _category_from_heading(line)
        if heading and len(line) <= 18:
            current_category = heading
            continue
        category = categorize_market_memo_line(line, current_category)
        if category != "기타":
            current_category = category
        score, tags = score_market_memo_line(line)
        tickers = _mentioned_tickers(line, extra_aliases)

        line_item = {
            "category": category,
            "text": line,
            "score": score,
            "tone": _tone_from_score(score, int("과열/확인" in tags)),
            "tags": tags,
            "tickers": tickers,
        }
        line_items.append(line_item)

        stat = category_stats[category]
        stat["score"] += score
        stat["count"] += 1
        if "과열/확인" in tags:
            stat["caution"] += 1
        if len(stat["examples"]) < 3:
            stat["examples"].append(line)

        for ticker in tickers:
            tstat = ticker_stats[ticker]
            tstat["score"] += score
            tstat["count"] += 1
            tstat["categories"].add(category)
            if "과열/확인" in tags:
                tstat["caution"] += 1
            if len(tstat["examples"]) < 2:
                tstat["examples"].append(line)

        if any(kw in _lower(line) for kw in SOURCE_CHECK_KEYWORDS) or _source_check_reason(line) != "출처 확인 필요":
            reason = _source_check_reason(line)
            if reason != "출처 확인 필요":
                verification_flags.append({
                    "중요도": "높음" if any(x in reason for x in ("비상장", "숫자", "매크로")) else "보통",
                    "항목": line,
                    "확인사유": reason,
                })

    category_rows = []
    for category, stat in category_stats.items():
        score = float(stat["score"])
        caution = int(stat["caution"])
        category_rows.append({
            "카테고리": category,
            "톤": _tone_from_score(score, caution),
            "점수": score,
            "뉴스수": int(stat["count"]),
            "확인필요": caution,
            "대표문장": " / ".join(stat["examples"][:2]),
        })
    category_rows.sort(key=lambda row: (abs(row["점수"]), row["뉴스수"]), reverse=True)

    explicit_ticker_rows = []
    for ticker, stat in ticker_stats.items():
        score = float(stat["score"])
        tone = _tone_from_score(score, int(stat["caution"]))
        explicit_ticker_rows.append({
            "티커": ticker,
            "연결방식": "직접언급",
            "영향": tone,
            "점수": score,
            "뉴스수": int(stat["count"]),
            "카테고리": ", ".join(sorted(stat["categories"])),
            "행동": _action_for_link(score, tone, True),
            "근거": " / ".join(stat["examples"][:2]),
        })

    category_score_map = {row["카테고리"]: row for row in category_rows}
    user_link_rows: list[dict] = []
    seen_user_tickers: set[str] = set()
    for item in universe or []:
        ticker = _norm(item.get("ticker", "")).upper()
        if not ticker or ticker in seen_user_tickers:
            continue
        seen_user_tickers.add(ticker)
        name = _norm(item.get("name", ticker))
        source = _norm(item.get("source", "관심"))

        explicit = ticker in ticker_stats
        if explicit:
            stat = ticker_stats[ticker]
            score = float(stat["score"])
            categories = sorted(stat["categories"])
            tone = _tone_from_score(score, int(stat["caution"]))
            user_link_rows.append({
                "종목": name,
                "티커": ticker,
                "구분": source,
                "연결방식": "직접언급",
                "영향": tone,
                "점수": score,
                "카테고리": ", ".join(categories),
                "오늘점검": _action_for_link(score, tone, True),
                "근거": " / ".join(stat["examples"][:2]),
            })
            continue

        exposures = infer_market_memo_exposures(item)
        matched = [category_score_map[cat] for cat in exposures if cat in category_score_map]
        matched = [row for row in matched if abs(float(row.get("점수", 0))) > 0 or int(row.get("확인필요", 0)) > 0]
        if not matched:
            continue
        best = sorted(matched, key=lambda row: (abs(float(row["점수"])), int(row["뉴스수"])), reverse=True)[0]
        score = float(best["점수"])
        tone = str(best["톤"])
        user_link_rows.append({
            "종목": name,
            "티커": ticker,
            "구분": source,
            "연결방식": "테마연결",
            "영향": tone,
            "점수": score,
            "카테고리": str(best["카테고리"]),
            "오늘점검": _action_for_link(score, tone, False),
            "근거": str(best["대표문장"]),
        })

    linked_tickers = {row["티커"] for row in user_link_rows}
    for row in explicit_ticker_rows:
        if row["티커"] not in linked_tickers:
            user_link_rows.append({
                "종목": row["티커"],
                "티커": row["티커"],
                "구분": "메모언급",
                "연결방식": row["연결방식"],
                "영향": row["영향"],
                "점수": row["점수"],
                "카테고리": row["카테고리"],
                "오늘점검": row["행동"],
                "근거": row["근거"],
            })

    user_link_rows.sort(key=lambda row: (row["구분"] == "보유", abs(float(row["점수"]))), reverse=True)

    total_score = sum(float(row["점수"]) for row in category_rows)
    total_caution = sum(int(row["확인필요"]) for row in category_rows)
    hot = [row["카테고리"] for row in category_rows if float(row["점수"]) >= 2]
    weak = [row["카테고리"] for row in category_rows if float(row["점수"]) <= -2]
    risk_context = _headline_risk_context(lines)
    if hot and risk_context["any"]:
        headline = f"{', '.join(hot[:2])} 중기 주도, 단기 로테이션/이벤트 확인 필요"
        action_bias = "레버리지 추격 금지 · 눌림/종가 확인 우선"
    elif risk_context["rotation"] and risk_context["event"]:
        headline = "중기 주도와 단기 로테이션이 엇갈림"
        action_bias = "FOMC/종가 확인 전 신규매수 보수"
    elif risk_context["leverage"] and total_caution >= 1:
        headline = "레버리지 후보는 조건부 관찰 구간"
        action_bias = "정해둔 DCA 외 추격 금지"
    elif hot and total_caution >= 2:
        headline = f"{', '.join(hot[:2])} 호재 우위지만 과열/출처 확인 필요"
        action_bias = "정밀관측 우선, 데이마켓 추격은 보수"
    elif hot:
        headline = f"{', '.join(hot[:2])} 호재 우위"
        action_bias = "강한 종목만 분할 후보"
    elif weak:
        headline = f"{', '.join(weak[:2])} 부담 우위"
        action_bias = "신규매수보다 리스크 점검"
    elif total_caution >= 2:
        headline = "재료는 많지만 확인 전 이벤트가 많음"
        action_bias = "출처 확인 후 정밀관측"
    else:
        headline = "시황 영향 혼조"
        action_bias = "가격·수급 신호 우선"

    return {
        "has_content": bool(lines),
        "headline": headline,
        "action_bias": action_bias,
        "total_score": total_score,
        "caution_count": total_caution,
        "category_rows": category_rows,
        "ticker_rows": user_link_rows,
        "verification_flags": verification_flags[:20],
        "line_items": line_items,
    }
