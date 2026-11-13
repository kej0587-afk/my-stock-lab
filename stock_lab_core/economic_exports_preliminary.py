"""Latest whole-month official exports release, separate from Customs final data."""

from copy import deepcopy
from datetime import date
import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from stock_lab_core import economic_releases as r
from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)
LIST_URL = "https://www.motir.go.kr/kor/article/ATCL3f49a5a8c"
SOURCE = "산업통상부 수출입동향 (잠정치)"


def _period(title):
    match = re.fullmatch(r"(\d{4})년(\d{1,2})월수출입동향", re.sub(r"\s+", "", title))
    return r._month(f"{match[1]}-{int(match[2]):02d}") if match else None


def parse_listing(html, now):
    entries = []
    for link in BeautifulSoup(html, "html.parser").select("a[href]"):
        period = _period(link.get_text(" ", strip=True))
        url = urlsplit(urljoin(LIST_URL, link["href"]))
        if (period and period < now.strftime("%Y-%m") and url.scheme == "https"
                and url.netloc == "www.motir.go.kr"
                and re.fullmatch(r"/kor/article/ATCL3f49a5a8c/\d+/view", url.path)):
            entries.append((period, "https://www.motir.go.kr" + url.path))
    if not entries:
        raise r._Unavailable("ministry_monthly_exports_not_found")
    return max(entries)


def parse_detail(html, period, now):
    page = BeautifulSoup(html, "html.parser")
    title, body = page.select_one(".detail-tit"), page.select_one(".detail-cont")
    if title is None or body is None or _period(title.get_text(" ", strip=True)) != period:
        raise r._Unavailable("ministry_exports_period_mismatch")
    days = []
    for item in page.select(".detail-info li"):
        label, value = item.find("em"), item.find("span")
        if label and value and label.get_text(strip=True) == "등록일":
            days.append(value.get_text(strip=True))
    if len(days) != 1:
        raise r._Unavailable("ministry_exports_release_date_missing")
    day = date.fromisoformat(days[0])
    if day > now.date() or day.strftime("%Y-%m") <= period:
        raise r._Unavailable("ministry_exports_release_date_invalid")
    compact = re.sub(r"\s+", "", body.get_text(" ", strip=True))
    year, month = period.split("-")
    # Only the total monthly export sentence, never imports, ICT or YTD totals.
    pattern = (r"총괄[】\]]?[‘'’]?" + year[-2:] + r"\.0?" + str(int(month))
               + r"월수출은전년동월대비(\d+(?:\.\d+)?)%(증가|감소)한([\d,]+(?:\.\d+)?)억달러")
    matches = re.findall(pattern, compact)
    if len(matches) != 1:
        raise r._Unavailable("ministry_exports_total_unverified")
    rate, direction, amount = matches[0]
    rate, amount = float(rate) * (-1 if direction == "감소" else 1), r._number(amount)
    if amount is None or amount <= 0 or rate < -100:
        raise r._Unavailable("ministry_exports_value_invalid")
    return dict(period=period, actual=rate, raw_actual=amount, raw_unit="억 달러",
                release_at=day.isoformat())


def load_preliminary_exports(now):
    now = r._clock(now)
    diagnostics = {name: {"http_status": None, "attempted": False} for name in ("listing", "detail")}

    def fetch():
        listing = r._request(LIST_URL, params={"searchKeyword": "수출입 동향"},
                             text=True, diagnostics=diagnostics["listing"])
        period, url = parse_listing(listing, now)
        detail = r._request(url, text=True, diagnostics=diagnostics["detail"])
        return dict(observation=parse_detail(detail, period, now), source_url=url,
                    diagnostics=deepcopy(diagnostics))

    data, error, retrieved = r._cached(("ministry_exports", now.date().isoformat()), fetch, now)
    row = r._row("KR_EXPORTS", "%", "YoY", SOURCE, LIST_URL, now,
                 retrieved_at=retrieved, series_id="ministry/monthly_preliminary",
                 data_vintage="preliminary_bulletin", value_kind="official_bulletin",
                 official_bulletin_fetch=True, fallback_mode="automatic_official")
    row["bulletin_request_metadata"] = deepcopy(data["diagnostics"] if data else diagnostics)
    if data:
        row.update(data["observation"], source_url=data["source_url"], status="released",
                   release_precision="date", release_source=SOURCE, release_source_url=data["source_url"])
        if row["period"] < r._shift(now.strftime("%Y-%m"), -1):
            row.update(status="stale")
            r._reason(row, "latest_completed_month_not_in_bulletin")
    else:
        r._reason(row, error or "ministry_exports_unavailable")
    r._finish(row)
    return row


def apply_preliminary_exports(rows, now):
    from stock_lab_core.economic_cache import retain_successful_observations

    for row in rows:
        if (row.get("indicator") != "KR_EXPORTS" or not row.get("official_bulletin_fetch")
                or row.get("status") == "pending" or row.get("value_kind") == "supplied_event"
                or row.get("basis") != "YoY" or row.get("unit") != "%"
                or (row.get("actual") is not None and row.get("period", "") >= r._shift(now.strftime("%Y-%m"), -1))):
            continue
        live = retain_successful_observations([load_preliminary_exports(now)], now)[0]
        # Final observations win for the same month. Never carry consensus or
        # price reactions across periods/providers when upgrading an observation.
        if live.get("actual") is not None and (row.get("actual") is None or live["period"] > row.get("period", "")):
            configured = row.get("api_key_configured")
            row.clear()
            row.update(live, api_key_configured=configured)
        else:
            row["preliminary_request_metadata"] = live.get("bulletin_request_metadata", {})
            row["preliminary_collection_reason"] = live.get("missing_reason", "older_period")
