"""Narrow report-only promotion filter, independent of investment scoring."""

import re

from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)


def is_financing_promotion(row):
    title = str(row.get("title") or row.get("제목") or "")
    product = re.search(r"신용\s*미수|신용.{0,5}(?:대출|융자|이자)|미수.{0,5}이자|스탁론|주식담보대출", title)
    offer = re.search(r"연\s*\d+(?:\.\d+)?\s*%\s*대?\s*(?:금리|이자)(?:로|부터)|이자\s*(?:무료|면제)|최저\s*금리|금리\s*혜택|갈아타|상담\s*신청|지금\s*신청", title)
    return bool(product and offer)


def without_promotions(rows):
    return [row for row in rows if not is_financing_promotion(row)]
