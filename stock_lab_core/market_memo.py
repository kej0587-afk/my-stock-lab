"""Market memo parser for the Today Check tab.

The parser intentionally treats pasted market notes as unverified input.  It
extracts sector tone, source-check flags, and portfolio/watchlist links without
calling external services.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
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
)
CAUTION_KEYWORDS = (
    "밈", "콜옵션", "yolo", "야간거래", "급증", "논의", "예정", "계획",
    "전자 서명", "ipo", "투자 라운드", "기업 가치", "채권 발행", "양해각서",
)
SOURCE_CHECK_KEYWORDS = (
    "밈", "콜옵션", "yolo", "야간거래", "전자 서명", "예정", "논의", "계획",
    "투자 라운드", "기업 가치", "ipo", "채권 발행", "비상장", "휴전",
)


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
    if hot and total_caution >= 2:
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
