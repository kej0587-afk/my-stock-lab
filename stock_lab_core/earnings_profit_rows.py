"""Split the earnings profit evidence into 영업이익 · 순이익 · GAAP EPS · 조정 EPS (2026-11-26 user request).

Each row keeps the complete source sentence (or the filing/PDF field) that states that measure; nothing is
computed or inferred. An EPS figure without a GAAP or non-GAAP label stays in its own "기준 미표기" row and is
never moved into the GAAP row, because an unlabelled figure beside a non-GAAP one is not proof of its basis.
"""
import re

from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)

OPERATING = "영업이익"
NET = "순이익"
EPS_GAAP = "GAAP EPS"
EPS_ADJ = "조정 EPS"
EPS_UNLABELLED = "EPS(회계기준 미표기)"
ROWS = (OPERATING, NET, EPS_GAAP, EPS_ADJ)

_OPERATING = re.compile(r"\boperating (?:income|profit|loss)\b|영업이익|영업손익|영업손실", re.I)
_NET = re.compile(r"\bnet (?:income|profit|loss|earnings)\b|순이익|순손실|순손익", re.I)
_EPS = re.compile(r"\bearnings per (?:diluted |basic )?share\b|\b(?:diluted |basic )?EPS\b|\bper (?:diluted |basic )?share\b|주당순이익", re.I)
# "net income per diluted share" names EPS only; "net income was $X, or $Y per diluted share" names both.
_NET_PER_SHARE = re.compile(r"\bnet (?:income|earnings|loss) per (?:diluted |basic )?share\b", re.I)
_ADJ = re.compile(r"\bnon-GAAP\b|\badjusted\b|\bnon-IFRS\b", re.I)
_GAAP = re.compile(r"(?<!non-)\bGAAP\b", re.I)
_MONEY = re.compile(r"\$\s*\(?[\d,.]+|\b(?:KRW|USD)\s*[\d,.]+|[\d,.]+\s*(?:billion|million|trillion)\b|[\d,.]+\s*(?:조원|억원|원)", re.I)


def _basis(clause):
    gaap, adjusted = bool(_GAAP.search(clause)), bool(_ADJ.search(clause))
    return "GAAP·조정" if gaap and adjusted else "GAAP" if gaap else "조정" if adjusted else "기준 미표기"


def classify_sentence(sentence):
    """{row: basis} for the measures this sentence states, clause by clause (';' separates clauses)."""
    found = {}
    for clause in re.split(r";\s*", str(sentence or "")):
        if not _MONEY.search(clause):
            continue
        basis = _basis(clause)
        if _OPERATING.search(clause):
            found.setdefault(OPERATING, basis)
        if _NET.search(_NET_PER_SHARE.sub("", clause)):
            found.setdefault(NET, basis)
        if _EPS.search(clause):
            if basis in ("GAAP", "GAAP·조정"):
                found.setdefault(EPS_GAAP, basis)
            if basis in ("조정", "GAAP·조정"):
                found.setdefault(EPS_ADJ, basis)
            if basis == "기준 미표기":
                found.setdefault(EPS_UNLABELLED, basis)
    return found


def breakdown_from_sentences(sentences, source_url):
    """First current-quarter sentence per row from already filtered source sentences."""
    rows = {}
    for sentence in sentences:
        for row, basis in classify_sentence(sentence).items():
            if row not in rows:
                rows[row] = {"status": "reported", "text": sentence, "basis": basis, "source_url": source_url}
    return rows


def profit_rows(metric):
    """{row: entry} for a stored profit metric, whatever source produced it (no new numbers)."""
    metric = metric if isinstance(metric, dict) else {}
    if metric.get("status") != "reported":
        return {}
    if isinstance(metric.get("breakdown"), dict):
        return metric["breakdown"]
    url = metric.get("source_url", "")
    rows = {}
    for comp in metric.get("components") or []:  # DART fields
        if not isinstance(comp, dict) or comp.get("status") != "reported":
            continue
        label = str(comp.get("label") or comp.get("text") or "")
        row = OPERATING if "영업" in label else NET if "순이익" in label else None
        if row and row not in rows:
            rows[row] = {"status": "reported", "text": comp.get("text", ""), "basis": "공시 재무제표",
                         "source_url": comp.get("source_url") or url}
    if rows:
        return rows
    label = str(metric.get("source_label") or "")
    if label:  # explicit PDF table row
        row = OPERATING if _OPERATING.search(label) else NET if _NET.search(label) else None
        if row:
            return {row: {"status": "reported", "text": metric.get("text", ""), "basis": "공식 표", "source_url": url}}
    return breakdown_from_sentences([metric.get("text", "")], url)
