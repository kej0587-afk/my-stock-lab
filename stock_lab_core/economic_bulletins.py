"""Automatic public ECOS CPI observations and Customs final bulletins.

The public board's search form and nttInfoBtn data attributes were verified on
2026-10-20. No guessed article ids, attachment downloads or third-party data.
Only collector-tagged rows opt into network fallback. The public ECOS sample
endpoint was verified on 2026-10-20: metadata and two four-month windows fit its
10-row limit. CPI is calculated from same-unit official index levels, never a
manually transcribed ministry citation. HTML/schema changes fail closed.
"""

from copy import deepcopy
from datetime import date
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.parse import urlencode

from stock_lab_core import economic_releases as releases
from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)

FACTS = Path(__file__).with_name("data") / "verified_kr_releases_20261019.json"
CUSTOMS_LIST_URL = "https://www.customs.go.kr/kcs/na/ntt/selectNttList.do"
CUSTOMS_DETAIL_URL = "https://www.customs.go.kr/kcs/na/ntt/selectNttInfo.do"
_TITLE = r"(\d{4})\ub144(\d{1,2})\uc6d4\uc6d4\uac04\uc218\ucd9c\uc785\ud604\ud669\[\ud655\uc815\uce58\]"
_MAX_HTML = 2_000_000


def _compact(text):
    return re.sub(r"\s+", "", text)


class _CustomsPage(HTMLParser):
    """Keep table boundaries/spans and board links without flattening nested tables."""

    def __init__(self, html):
        super().__init__()
        if not isinstance(html, str) or len(html) > _MAX_HTML:
            raise releases._Unavailable("customs_invalid_page")
        self.tables, self.stack, self.text, self.ignored = [], [], [], None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.ignored = tag
        if self.ignored:
            return
        attrs = dict(attrs)
        if tag == "table":
            if len(self.tables) + len(self.stack) >= 200:
                raise releases._Unavailable("customs_table_limit")
            self.stack.append({"attrs": attrs, "rows": [], "row": None, "cell": None,
                               "context": _compact("".join(self.text))[-300:]})
        if not self.stack:
            return
        table = self.stack[-1]
        if tag == "tr":
            table["row"] = {"cells": [], "links": []}
        elif tag in {"td", "th"} and table["row"] is not None:
            table["cell"] = {"attrs": attrs, "text": []}
        elif tag == "a" and table["row"] is not None:
            table["row"]["links"].append(attrs)

    def handle_data(self, data):
        if self.ignored:
            return
        self.text.append(data)
        if self.stack and self.stack[-1]["cell"] is not None:
            self.stack[-1]["cell"]["text"].append(data)

    def handle_endtag(self, tag):
        if tag == self.ignored:
            self.ignored = None
        if self.ignored or not self.stack:
            return
        table = self.stack[-1]
        if tag in {"td", "th"} and table["cell"] is not None:
            cell = table["cell"]
            cell["text"] = _compact("".join(cell["text"]))
            table["row"]["cells"].append(cell)
            table["cell"] = None
        elif tag == "tr" and table["row"] is not None:
            table["rows"].append(table["row"])
            table["row"] = None
        elif tag == "table":
            self.tables.append(self.stack.pop())


def _customs_listing(html, now):
    page = _CustomsPage(html)
    entries = []
    for table in page.tables:
        if "bbsList" not in table["attrs"].get("class", "").split():
            continue
        for row in table["rows"][:50]:
            days = [cell["text"] for cell in row["cells"]
                    if cell["attrs"].get("data-table") == "date"]
            if len(days) != 1:
                continue
            try:
                day = date.fromisoformat(days[0].replace(".", "-"))
            except ValueError:
                continue
            for link in row["links"]:
                title = _compact(link.get("title", ""))
                match = re.fullmatch(_TITLE, title)
                if not match or "nttInfoBtn" not in link.get("class", "").split():
                    continue
                period = releases._month(f"{match[1]}-{int(match[2]):02d}")
                article, token = link.get("data-id", ""), link.get("data-url", "")
                if (not period or not re.fullmatch(r"\d{1,12}", article)
                        or not re.fullmatch(r"[a-fA-F0-9]{32}", token)
                        or not period < day.strftime("%Y-%m") or day > now.date()):
                    continue
                entries.append({"period": period, "release_at": day.isoformat(), "title": title,
                                "nttSn": article, "nttSnUrl": token})
    if not entries:
        raise releases._Unavailable("customs_monthly_final_not_found")
    return max(entries, key=lambda entry: (entry["period"], entry["release_at"], int(entry["nttSn"])))


def _table_grid(table):
    grid = {}
    if len(table["rows"]) > 64:
        raise releases._Unavailable("customs_table_limit")
    for y, row in enumerate(table["rows"]):
        x = 0
        for cell in row["cells"]:
            while (y, x) in grid:
                x += 1
            width = int(cell["attrs"].get("colspan", "1"))
            height = int(cell["attrs"].get("rowspan", "1"))
            if not 1 <= width <= 16 or not 1 <= height <= 64 or x + width > 32 or y + height > 64:
                raise releases._Unavailable("customs_table_span_invalid")
            for dy in range(height):
                for dx in range(width):
                    if (y + dy, x + dx) in grid:
                        raise releases._Unavailable("customs_table_span_overlap")
                    grid[y + dy, x + dx] = cell["text"]
            x += width
    return grid


def _customs_observation(html, entry):
    page = _CustomsPage(html)
    if entry["title"] not in _compact("".join(page.text)):
        raise releases._Unavailable("customs_title_mismatch")
    dates = []
    for table in page.tables:
        if "bbsView" in table["attrs"].get("class", "").split():
            for row in table["rows"]:
                cells = [cell["text"] for cell in row["cells"]]
                dates.extend(cells[i + 1].replace(".", "-") for i, cell in enumerate(cells[:-1])
                             if cell == "\ub4f1\ub85d\uc77c")
    if dates != [entry["release_at"]]:
        raise releases._Unavailable("customs_publication_date_mismatch")
    candidates = []
    for table in page.tables:
        if "\ub2e8\uc704:\ubc31\ub9cc\ub2ec\ub7ec,%" not in table["context"]:
            continue
        grid = _table_grid(table)
        export_rows = [y for (y, x), text in grid.items()
                       if x == 0 and text == "\uc218\ucd9c(\uc804\ub144\ub3d9\uae30\ub300\ube44)"]
        if len(export_rows) != 1 or grid.get((0, 0)) != "\uad6c\ubd84":
            continue
        values = {}
        for x in range(1, 32):
            year = re.fullmatch(r"(\d{4})\ub144", grid.get((0, x), ""))
            month = re.fullmatch(r"(\d{1,2})\uc6d4", grid.get((1, x), ""))
            if not year or not month:
                continue  # Cumulative columns (1~9 month) are never monthly values.
            period = releases._month(f"{year[1]}-{int(month[1]):02d}")
            value = re.fullmatch(r"([\d,]+(?:\.\d+)?)\(([+\-\u2212\u25b3]?\d+(?:\.\d+)?)\)",
                                 grid.get((export_rows[0], x), ""))
            if not period or not value or period in values:
                raise releases._Unavailable("customs_export_cell_invalid")
            amount = releases._number(value[1])
            rate = releases._number(value[2].replace("\u25b3", "-").replace("\u2212", "-"))
            if amount is None or amount <= 0 or rate is None or rate < -100:
                raise releases._Unavailable("customs_export_cell_invalid")
            values[period] = (amount, rate)
        period = entry["period"]
        year_ago = releases._shift(period, -12)
        if period not in values or year_ago not in values:
            continue
        amount, rate = values[period]
        baseline = values[year_ago][0]
        if abs((amount / baseline - 1) * 100 - rate) > 0.15:
            raise releases._Unavailable("customs_export_rate_mismatch")
        previous_period = releases._shift(period, -1)
        candidates.append({"period": period, "actual": rate,
                           "previous": values.get(previous_period, (None, None))[1],
                           "previous_period": previous_period,
                           "raw_actual": amount, "raw_year_ago": baseline,
                           "raw_year_ago_period": year_ago, "raw_unit": "\ubc31\ub9cc \ub2ec\ub7ec",
                           "release_at": entry["release_at"]})
    if len(candidates) != 1:
        raise releases._Unavailable("customs_export_table_unverified")
    return candidates[0]


def load_kr_exports_bulletin(now):
    """At most two public requests, using the existing timeout and success cache."""
    now = releases._clock(now)
    diagnostics = {"listing": {"http_status": None}, "detail": {"http_status": None}}

    def fetch():
        html = releases._request(CUSTOMS_LIST_URL, text=True, diagnostics=diagnostics["listing"],
                                 params={"bbsId": "1362", "mi": "2891", "searchType": "sj",
                                         "searchValue": "\uc6d4\uac04 \uc218\ucd9c\uc785 \ud604\ud669", "listCo": "10"})
        entry = _customs_listing(html, now)
        params = {"bbsId": "1362", "mi": "2891", "nttSn": entry["nttSn"], "nttSnUrl": entry["nttSnUrl"]}
        html = releases._request(CUSTOMS_DETAIL_URL, params=params, text=True, diagnostics=diagnostics["detail"])
        observation = _customs_observation(html, entry)
        return {"observation": observation, "source_url": CUSTOMS_DETAIL_URL + "?" + urlencode(params),
                "request": deepcopy(diagnostics)}

    data, error, retrieved = releases._cached(("customs_exports", now.date().isoformat()), fetch, now)
    row = releases._row("KR_EXPORTS", "%", "YoY", "Korea Customs Service (monthly final bulletin)",
                        CUSTOMS_LIST_URL, now, seasonal_adjustment="NSA", retrieved_at=retrieved,
                        value_kind="official_bulletin", official_bulletin_fetch=True,
                        fallback_mode="automatic_official", data_vintage="final_bulletin")
    row["bulletin_request_metadata"] = deepcopy(data["request"] if data else diagnostics)
    row["bulletin_request_metadata"]["from_cache"] = bool(data and diagnostics["listing"]["http_status"] is None)
    if not data:
        releases._reason(row, error)
        return row
    row.update(data["observation"], source_url=data["source_url"], status="released",
               release_source=row["source"], release_source_url=data["source_url"], release_precision="date",
               previous_source=row["source"], previous_unit="%", previous_basis="YoY")
    row["observation_recency"] = "latest_completed_month"
    if row["period"] != releases._shift(now.strftime("%Y-%m"), -1):
        row.update(status="stale", observation_recency="older_period")
        releases._reason(row, "latest_completed_month_not_in_bulletin")
    releases._finish(row)
    return row


def load_kr_cpi_bulletin(now):
    """Three bounded public requests; no configured credentials are accessed.

    Four recent index levels plus their exact year-ago months supply actual,
    previous and the three consecutive prior YoY observations. This is a small
    public-sample fallback, not an archive or a guarantee of future availability.
    """
    now = releases._clock(now)
    end = releases._shift(now.strftime("%Y-%m"), -1)
    start = releases._shift(end, -3)
    windows = {"current": (start, end),
               "year_ago": (releases._shift(start, -12), releases._shift(end, -12))}
    metadata_url = releases.ECOS_URL + "StatisticItemList/sample/json/kr/1/10/901Y009"
    urls = {name: releases.ECOS_URL + "StatisticSearch/sample/json/kr/1/10/901Y009/M/"
                  + first.replace("-", "") + "/" + last.replace("-", "") + "/0"
            for name, (first, last) in windows.items()}
    diagnostics = {name: {"http_status": None} for name in ("metadata", "current", "year_ago")}

    def fetch():
        meta = releases._ecos_metadata(releases._request(metadata_url, diagnostics=diagnostics["metadata"]), "KR_CPI")
        levels = {}
        for name, (first, last) in windows.items():
            payload = releases._request(urls[name], diagnostics=diagnostics[name])
            values = releases._ecos_levels(payload, "KR_CPI", meta["unit"], first, last)
            if not values:
                raise releases._Unavailable("ecos_cpi_" + name + "_months_unavailable")
            levels.update(values)
        current = [period for period in levels if start <= period <= end]
        if releases._shift(max(current), -12) not in levels:
            raise releases._Unavailable("ecos_cpi_exact_year_ago_unavailable")
        return {"levels": levels, "unit": meta["unit"], "request": deepcopy(diagnostics)}

    data, error, retrieved = releases._cached(("ecos_public_cpi", end), fetch, now)
    row = releases._row("KR_CPI", "%", "YoY", "Bank of Korea ECOS", urls["current"], now,
                        seasonal_adjustment="NSA", series_id="901Y009/0", retrieved_at=retrieved,
                        value_kind="calculated_from_official_levels", official_bulletin_fetch=True,
                        fallback_mode="automatic_official", fallback_access="public_sample",
                        fallback_limitations="public_sample_max_10_rows;four_recent_months_only;latest_revised_vintage",
                        source_urls=[metadata_url, urls["current"], urls["year_ago"]])
    row["bulletin_request_metadata"] = deepcopy(data["request"] if data else diagnostics)
    row["bulletin_request_metadata"]["from_cache"] = bool(data and diagnostics["metadata"]["http_status"] is None)
    if not data:
        releases._reason(row, error)
        return row
    releases._ecos_rates(row, data["levels"], data["unit"])
    row["observation_recency"] = "latest_completed_month"
    if row["period"] != end:
        row.update(status="stale", observation_recency="older_period")
        releases._reason(row, "latest_completed_month_not_in_response")
    releases._finish(row)
    return row


def _apply_live_cpi(rows, now):
    from stock_lab_core.economic_cache import retain_successful_observations

    for row in rows:
        if (row.get("indicator") != "KR_CPI" or row.get("basis") != "YoY" or row.get("unit") != "%"
                or row.get("value_kind") == "supplied_event" or row.get("status") == "pending"):
            continue
        if not row.get("official_bulletin_fetch"):
            if row.get("actual") is None:
                row.update(fallback_mode="unavailable", bulletin_collection_error="cpi_primary_automatic_fetch_not_enabled")
            continue
        if (row.get("status") == "released" and row.get("actual") is not None
                and row.get("period") == releases._shift(now.strftime("%Y-%m"), -1)
                and row.get("previous") is not None and row.get("previous3mean") is not None):
            continue
        live = load_kr_cpi_bulletin(now)
        if live["actual"] is not None and (row.get("actual") is None or live["period"] >= row.get("period", "")):
            configured = row.get("api_key_configured")
            failure = row.get("collection_error") or row.get("missing_reason") or "provider_history_incomplete"
            # The sample publishes levels, not dates. Keep an already sourced date
            # only when it belongs to this exact observation and comparison basis.
            if (row.get("period") == live["period"] and row.get("release_at")
                    and row.get("release_source") and row.get("release_source_url")
                    and not releases._future(row, now)):
                for field in ("release_at", "release_precision", "release_source", "release_source_url"):
                    live[field] = row.get(field)
                live["missing_reason"] = ";".join(code for code in live["missing_reason"].split(";")
                                                  if code != "release_date_unavailable")
            live = retain_successful_observations([live], now)[0]
            row.clear()
            row.update(live, api_key_configured=configured, primary_collection_error=failure)
        else:
            row["bulletin_request_metadata"] = live["bulletin_request_metadata"]
            row["bulletin_source_url"] = live["source_url"]
            if live["actual"] is None:
                row["bulletin_collection_error"] = live["missing_reason"]
                row.setdefault("missing_reason", "")
                releases._reason(row, "cpi_automatic_primary_unavailable")
            else:
                row["bulletin_not_applied"] = "newer_observation_preserved"


def _apply_live_exports(rows, now):
    from stock_lab_core.economic_cache import retain_successful_observations

    for row in rows:
        if (row.get("indicator") != "KR_EXPORTS" or not row.get("official_bulletin_fetch")
                or row.get("basis") != "YoY" or row.get("unit") != "%"
                or row.get("value_kind") == "supplied_event" or row.get("status") == "pending"):
            continue
        if (row.get("actual") is not None and row.get("status") == "released"
                and row.get("period", "") >= releases._shift(now.strftime("%Y-%m"), -1)):
            continue
        live = load_kr_exports_bulletin(now)
        if (live["actual"] is not None
                and (row.get("actual") is None or live["period"] > row.get("period", "")
                     or (live["period"] == row.get("period")
                         and row.get("value_kind") in {"official_bulletin", "verified_official_bulletin"}))):
            configured = row.get("api_key_configured")
            failure = row.get("collection_error") or row.get("missing_reason") or "older_provider_period"
            live = retain_successful_observations([live], now)[0]
            row.clear()
            row.update(live, api_key_configured=configured, primary_collection_error=failure)
        else:
            row["bulletin_request_metadata"] = live["bulletin_request_metadata"]
            if live["actual"] is None:
                row["bulletin_collection_error"] = live["missing_reason"]
            else:
                row["bulletin_not_applied"] = "existing_period_or_vintage_preserved"


def apply_official_bulletins(rows, now):
    now = releases._clock(now)
    result = deepcopy(rows)
    _apply_live_cpi(result, now)
    _apply_live_exports(result, now)
    try:
        facts = json.loads(FACTS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return result
    if not facts["verified_at"] <= now.date().isoformat() < facts["expires_at"]:
        return result
    for row in result:
        if row.get("status") == "pending" or row.get("value_kind") == "supplied_event":
            continue
        for fact in facts["observations"]:
            if fact.get("indicator") == "KR_CPI":
                continue
            if (row.get("indicator") != fact["indicator"] or row.get("basis") != fact["basis"]
                    or row.get("unit") != fact["unit"]):
                continue
            if row.get("period", "") >= fact["period"] and row.get("actual") is not None:
                continue
            # Do not carry a different month's consensus, revision or price reaction.
            configured = row.get("api_key_configured")
            failure = row.get("collection_error") or row.get("missing_reason") or "older_provider_period"
            diagnostics = {key: row[key] for key in ("official_bulletin_fetch", "bulletin_request_metadata",
                                                    "bulletin_collection_error") if key in row}
            row.clear()
            row.update(fact, status="verified_snapshot", collection_error=failure, api_key_configured=configured,
                       as_of=now.isoformat(), verified_at=facts["verified_at"], expires_at=facts["expires_at"], forecast=None, history=[],
                       release_precision="date", value_kind="verified_official_bulletin",
                       previous_unit=fact["unit"], previous_basis=fact["basis"], previous_source=fact["source"],
                       fallback_mode="manual_verified", **diagnostics)
    return result
