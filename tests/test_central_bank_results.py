"""Synthetic official layouts and offline transports; not stored rate facts."""

from datetime import datetime, timedelta
from io import BytesIO

import pytest
import requests
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from stock_lab_core import central_bank_results as results

NOW = datetime.fromisoformat("2026-10-30T13:00:00+09:00")
FED_DAY = NOW.date().replace(day=28)
BOJ_DAY = NOW.date()
FED_URL = "https://www.federalreserve.gov/newsevents/pressreleases/monetary20261028a.htm"
BOJ_URL = "https://www.boj.or.jp/en/mopo/mpmdeci/mpr_2026/k261030a.pdf"
FED = b'''<h3>Federal Reserve issues FOMC statement</h3>
<p class="article__time">October 28, 2026</p><p>For release at 2:00 p.m. EDT</p>
<p>The Committee decided to maintain the target range for the federal funds rate at 3-3/4 to 4 percent.</p>'''
BOJ = """October 30, 2026 Bank of Japan Statement on Monetary Policy
1. Guideline for money market operations (an 8-1 majority vote)[Note]
At the Monetary Policy Meeting (MPM) held today, the Policy Board of the Bank of Japan
decided to set the following guideline for money market operations for the intermeeting period:
The Bank will encourage the uncollateralized overnight call rate to remain at around 1.25 percent.
[Note] Voting against the action: a member proposed around 1.5 percent.
Release dates and times: Statement on Monetary Policy -- Friday, October 30 at 12:02
Outlook Report -- Monday, November 2 at 14:00"""
CALENDAR = b'''<h4>2026 FOMC Meetings</h4><div class="fomc-meeting">
<div class="fomc-meeting__month">October</div><div class="fomc-meeting__date">27-28</div>
<a href="/newsevents/pressreleases/monetary20261028a.htm">HTML</a></div>'''
BOJ_CALENDAR = b'''<table><caption>Table : 2026</caption><tr><td>
Oct. 29 (Thurs.), 30 (Fri.)</td><td>Oct. 30 (Fri.)</td></tr></table>'''
BOK_VIEW_URL = "https://www.bok.or.kr/portal/bbs/P0000559/view.do?nttId=11000001&menuNo=200690"
# Layout from the 2026-11-26 BOK page survey (docs/maintenance/20261126_bok_mpc_source_structure.md); rates are synthetic.
BOK_MAIN = """<html><head><meta charset="utf-8"></head><body><ul>
<li><a href="/portal/bbs/P0000559/view.do?nttId=11000001&amp;menuNo=200690">통화정책방향 (2026.10.22)</a></li>
<li><a href="/portal/bbs/P0000559/view.do?nttId=10900000&amp;menuNo=200690">보도자료 (2026.10.21)</a></li>
</ul></body></html>""".encode("utf-8")
BOK_VIEW = """<html><head><meta charset="utf-8"><title>통화정책방향(2026.10.22) | 통화정책 보도자료(상세) | 한국은행</title></head>
<body><dl><dt class="sr-only">등록일</dt><dd class="date">2026.10.22</dd></dl>
<div class="dbdata"><p>□ 금융통화위원회는 다음 통화정책방향 결정시까지 한국은행 기준금리를 현재의 2.75% 수준에서 3.00% 로
상향 조정하여 통화정책을 운용하기로 하였다 .</p><p>□ 세계경제는 성장세가 둔화되었으며 기준금리를 3.50%로 인상한 국가도 있었다.</p></div>
</body></html>""".encode("utf-8")
BOJ_LIST = b'''<table><tr><td>Oct. 30, 2026</td><td><a href="/en/mopo/mpmdeci/mpr_2026/k261030a.pdf">
Statement on Monetary Policy [PDF 172KB]</a></td></tr></table>'''


def make_pdf(body):
    writer = PdfWriter()
    page = writer.add_blank_page(612, 792)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                             NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
    escaped = body.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = DecodedStreamObject()
    stream.set_data(("BT /F1 10 Tf 10 700 Td (" + escaped + ") Tj ET").encode("ascii"))
    page[NameObject("/Contents")] = stream
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    results.clear_central_bank_results_cache()
    monkeypatch.setattr(results.requests, "get", lambda *a, **k: pytest.fail("Unexpected network"))
    yield
    results.clear_central_bank_results_cache()


@pytest.fixture
def transport(monkeypatch):
    state = dict(calls=[], closed=[], status=200, error=None, pages={
        results.FOMC_URL: CALENDAR, results.BOJ_CALENDAR_URL: BOJ_CALENDAR,
        results.BOJ_STATEMENTS_URL.format(year=2026): BOJ_LIST,
        FED_URL: FED, BOJ_URL: make_pdf(BOJ),
        results.BOK_MAIN_URL: BOK_MAIN, BOK_VIEW_URL: BOK_VIEW,
    })

    class Response:
        def __init__(self, url):
            self.status_code, self.headers, self.url = state["status"], {}, url

        def iter_content(self, chunk_size):
            yield state["pages"][self.url]

        def close(self):
            state["closed"].append(self.url)

    def get(url, **kwargs):
        assert kwargs["timeout"] == (2.0, 3.0)
        assert kwargs["allow_redirects"] is False and kwargs["stream"] is True
        state["calls"].append(url)
        if state["error"]:
            raise state["error"]
        return Response(url)

    monkeypatch.setattr(results.requests, "get", get)
    return state


def test_fetch_official_dates_rates_cache_and_mutation_isolation(transport):
    fed, boj, bok = results.fetch_central_bank_results(NOW)
    assert (fed["status"], boj["status"], bok["status"]) == ("official", "official", "official")
    assert (bok["decision_date"], bok["date"], bok["source_url"]) == ("2026-10-22", "2026-10-22", BOK_VIEW_URL)
    assert (bok["previous_rate"], bok["policy_rate"], bok["action"]) == (2.75, 3.0, "hike")
    assert bok["release_at"] is None and bok["release_precision"] == "date"
    assert fed["decision_date"] == "2026-10-28" and fed["date"] == "2026-10-29"
    assert fed["release_at"] == "2026-10-28T14:00:00-04:00"
    assert (fed["rate_lower"], fed["rate_upper"], fed["action"]) == (3.75, 4.0, "hold")
    assert boj["release_at"] == "2026-10-30T12:02:00+09:00"
    assert boj["policy_rate"] == 1.25 and boj["date"] == "2026-10-30"
    assert boj["action"] == "set_target"  # Not inferred from "remain at around".
    assert len(transport["calls"]) == len(transport["closed"]) == 7
    fed["rate_lower"] = 999
    cached = results.fetch_central_bank_results(NOW + timedelta(minutes=1))
    assert all(row["from_cache"] for row in cached)
    assert cached[0]["rate_lower"] == 3.75 and len(transport["calls"]) == 7


@pytest.mark.parametrize("replace,reason", [
    ((b"October 28, 2026", b"October 29, 2026"), "decision_date_mismatch"),
    ((b"EDT", b"EST"), "release_timezone_mismatch"),
    ((b"The Committee decided", b"Analysts expect"), "policy_decision_unrecognized"),
    ((b"FOMC statement", b"FOMC minutes"), "statement_identity_mismatch"),
    ((b"For release at 2:00 p.m. EDT", b"For immediate release"), "release_time_unconfirmed"),
])
def test_fed_rejects_unverified_decisions(replace, reason):
    with pytest.raises(ValueError, match=reason):
        results._fed_result(FED.replace(*replace), FED_DAY, NOW)


@pytest.mark.parametrize("numbers,expected", [
    (b"3 3/4 to 4", (3.75, 4)), (b"1/4 to 1/2", (.25, .5)),
    (b"0 to 0.25", (0, .25)),
])
def test_fed_fraction_variants(numbers, expected):
    row = results._fed_result(FED.replace(b"3-3/4 to 4", numbers), FED_DAY, NOW)
    assert (row["rate_lower"], row["rate_upper"]) == expected


def test_fed_cut_and_dissent_do_not_replace_adopted_rate():
    data = FED.replace(b"maintain", b"lower").replace(b"at 3-3/4", b"by 1/4 percentage point to 3-3/4")
    data += b"<p>One voter preferred to raise the rate to 5 percent.</p>"
    assert results._fed_result(data, FED_DAY, NOW)["action"] == "cut"


def test_fed_sentence_prefix_and_different_year_are_supported():
    data = FED.replace(b"The Committee", b"In support of its goals, the Committee")
    data = data.replace(b"2026", b"2027")
    row = results._fed_result(data, FED_DAY.replace(year=2027), NOW.replace(year=2027))
    assert row["date"] == "2027-10-29" and row["action"] == "hold"


def test_before_release_does_not_leak_future_result_from_cache(transport):
    results.fetch_central_bank_results(NOW)
    earlier = results.fetch_central_bank_results(NOW.replace(hour=11))
    assert earlier[1]["status"] == "missing" and earlier[1]["policy_rate"] is None
    assert earlier[1]["reason"] == "release_after_report_time"
    assert not earlier[1]["from_cache"]
    with pytest.raises(ValueError, match="release_after_report_time"):
        results._fed_result(FED, FED_DAY, datetime.fromisoformat("2026-10-28T17:59:00+00:00"))


def test_boj_dated_result_without_time_fails_closed_same_day():
    data = make_pdf(BOJ.split("Release dates and times:")[0])
    with pytest.raises(ValueError, match="same_day_release_time_unconfirmed"):
        results._boj_result(data, BOJ_DAY, NOW)
    row = results._boj_result(data, BOJ_DAY, NOW + timedelta(days=1))
    assert row["release_at"] is None and row["release_precision"] == "date"


def test_boj_statement_date_and_link_date_must_match():
    with pytest.raises(ValueError, match="decision_date_mismatch"):
        results._boj_result(make_pdf(BOJ.replace("October 30, 2026", "September 18, 2026")), BOJ_DAY, NOW)
    with pytest.raises(ValueError, match="official_statement_link_unavailable"):
        results._statement_link(BOJ_LIST.replace(b"k261030a.pdf", b"k260918a.pdf"), "BOJ", BOJ_DAY, results.BOJ_CALENDAR_URL)


def test_boj_reference_and_external_documents_not_decisions():
    for data in (BOJ_LIST.replace(b"Statement on Monetary Policy", b"(Reference) Statement on Monetary Policy"),
                 BOJ_LIST.replace(b'href="/', b'href="https://attacker.example/')):
        with pytest.raises(ValueError, match="official_statement_link_unavailable"):
            results._statement_link(data, "BOJ", BOJ_DAY, results.BOJ_CALENDAR_URL)


def test_dont_substitute_previous_meeting_when_current_statement_missing(transport):
    transport["pages"][results.BOJ_STATEMENTS_URL.format(year=2026)] = BOJ_LIST.replace(b"Oct. 30", b"Sept. 18")
    boj = results.fetch_central_bank_results(NOW)[1]
    assert boj["scheduled_date"] == "2026-10-30" and boj["date"] is None
    assert boj["status"] == "missing" and boj["fact"] is None
    assert boj["reason"] == "official_statement_link_unavailable"


@pytest.mark.parametrize("status", [302, 404, 429, 500])
def test_http_failure_closed_not_cached_and_retry_recovers(transport, status):
    transport["status"] = status
    rows = results.fetch_central_bank_results(NOW)
    assert len(transport["calls"]) == len(transport["closed"]) == 3
    assert all(row["status"] == "missing" and row["reason"] == f"http_{status}" for row in rows)
    transport["status"] = 200
    assert all(row["status"] == "official" for row in results.fetch_central_bank_results(NOW))


def test_timeouts_are_redacted_and_independent(transport):
    transport["error"] = requests.ReadTimeout("secret-url-token")
    rows = results.fetch_central_bank_results(NOW)
    assert all(row["reason"] == "request_failed:ReadTimeout" for row in rows)
    assert len(transport["calls"]) == 3


def test_document_size_and_cache_expiry(transport, monkeypatch):
    monkeypatch.setattr(results, "MAX_BYTES", 100)
    assert all(row["status"] == "missing" for row in results.fetch_central_bank_results(NOW))
    monkeypatch.setattr(results, "MAX_BYTES", 4_000_000)
    results.fetch_central_bank_results(NOW)
    calls = len(transport["calls"])
    monkeypatch.setattr(results, "CACHE_TTL", 0)
    results.fetch_central_bank_results(NOW)
    assert len(transport["calls"]) == calls + 7


def test_year_rollover_uses_calendar_year_not_current_constants():
    calendar = BOJ_CALENDAR.replace(b"2026", b"2028").replace(b"Oct. 29 (Thurs.), 30 (Fri.)", b"Jan. 20 (Thurs.), 21 (Fri.)")
    now = NOW.replace(year=2028, month=1, day=22)
    assert results._boj_meeting_day(calendar, now).isoformat() == "2028-01-21"


def test_cache_is_bounded(transport, monkeypatch):
    monkeypatch.setattr(results, "_load_bank", lambda bank, now: dict(status="official", bank=bank))
    for n in range(25):
        results.fetch_central_bank_results(NOW + timedelta(days=n))
    assert len(results._CACHE) == 16


def test_request_budget_prevents_starting_another_request():
    with pytest.raises(ValueError, match="collection_deadline"):
        results._request(results.FOMC_URL, -1)


def test_invalid_pdf_and_duplicate_policy_values_fail_closed():
    with pytest.raises(ValueError, match="invalid_pdf"):
        results._boj_result(b"not a PDF", BOJ_DAY, NOW)
    duplicate = FED + b"<p>The Committee decided to maintain the target range for the federal funds rate at 4 to 5 percent.</p>"
    with pytest.raises(ValueError, match="policy_decision_unrecognized"):
        results._fed_result(duplicate, FED_DAY, NOW)


def test_pdf_layout_extraction_and_metadata_cutoff(monkeypatch):
    import pypdf

    class Page:
        def extract_text(self, *, extraction_mode):
            assert extraction_mode == "layout"
            return BOJ

    class Reader:
        pages = [Page()]
        is_encrypted = False
        metadata = type("Metadata", (), {"modification_date": None, "creation_date": None})()

    monkeypatch.setattr(pypdf, "PdfReader", lambda *args: Reader())
    assert results._boj_result(b"%PDF-test", BOJ_DAY, NOW)["policy_rate"] == 1.25
    Reader.metadata.modification_date = NOW + timedelta(minutes=1)
    with pytest.raises(ValueError, match="document_version_after_report_time"):
        results._boj_result(b"%PDF-test", BOJ_DAY, NOW)


def test_one_bank_failure_does_not_hide_other_result(transport):
    transport["pages"][FED_URL] = b"<p>Unavailable</p>"
    fed, boj, bok = results.fetch_central_bank_results(NOW)
    assert fed["status"] == "missing" and boj["status"] == "official" and bok["status"] == "official"


BOK_DAY = NOW.date().replace(day=22)


@pytest.mark.parametrize("sentence,expected", [
    ("기준금리를 현재의 2.75% 수준에서 3.00% 로 상향 조정하여", (2.75, 3.0, "hike")),
    ("기준금리를 현재의 3.25%에서 3.00%로 인하하여", (3.25, 3.0, "cut")),
    ("기준금리를 현 수준(2.50%)에서 유지하여", (2.5, 2.5, "hold")),
    ("기준금리를 현재의 2.50% 수준에서 동결하여", (2.5, 2.5, "hold")),
])
def test_bok_decision_sentence_variants(sentence, expected):
    data = BOK_VIEW.replace("기준금리를 현재의 2.75% 수준에서 3.00% 로\n상향 조정하여".encode("utf-8"), sentence.encode("utf-8"))
    row = results._bok_result(data, BOK_DAY)
    assert (row["previous_rate"], row["policy_rate"], row["action"]) == expected


@pytest.mark.parametrize("old,new,reason", [
    ("통화정책방향(2026.10.22)", "통화정책방향(2026.08.27)", "decision_date_mismatch"),
    ('<dd class="date">2026.10.22</dd>', '<dd class="date">2026.10.23</dd>', "registration_date_mismatch"),
    ("3.00% 로\n상향", "2.50% 로\n상향", "policy_direction_mismatch"),
    ("□ 금융통화위원회는", "□ 시장에서는 금융통화위원회가", "policy_decision_unrecognized"),
    ("한국은행 기준금리를 현재의", "한국은행 정책금리를 현재의", "policy_decision_unrecognized"),
    ('class="dbdata"', 'class="other"', "policy_decision_unrecognized"),
])
def test_bok_rejects_unverified_pages(old, new, reason):
    with pytest.raises(ValueError, match=reason):
        results._bok_result(BOK_VIEW.replace(old.encode("utf-8"), new.encode("utf-8")), BOK_DAY)


def test_bok_later_paragraph_rate_is_not_the_decision():
    row = results._bok_result(BOK_VIEW, BOK_DAY)
    assert row["policy_rate"] == 3.0  # 3.50% in the second paragraph is another country's move


def test_bok_link_must_match_meeting_day_and_official_view():
    assert results._bok_statement_link(BOK_MAIN, BOK_DAY) == BOK_VIEW_URL
    with pytest.raises(ValueError, match="statement_for_meeting_not_posted"):
        results._bok_statement_link(BOK_MAIN.replace(b"2026.10.22", b"2026.08.27"), BOK_DAY)
    with pytest.raises(ValueError, match="official_statement_link_unavailable"):
        results._bok_statement_link(BOK_MAIN.replace(b"/portal/bbs/P0000559/view.do", b"https://example.com/view.do"), BOK_DAY)
    with pytest.raises(ValueError, match="official_statement_link_unavailable"):
        results._bok_statement_link(b"<html><body><a href='/x'>news</a></body></html>", BOK_DAY)


def test_bok_url_allowlist_and_schedule():
    assert results._official_url(BOK_VIEW_URL) and results._official_url(results.BOK_MAIN_URL)
    assert not results._official_url(BOK_VIEW_URL + "&x=1")
    assert not results._official_url("https://www.bok.or.kr/portal/bbs/B0000169/view.do?nttId=1&menuNo=200690")
    assert results._bok_meeting_day(datetime.fromisoformat("2026-11-26T10:00:00+09:00")).isoformat() == "2026-11-26"
    assert results._bok_meeting_day(datetime.fromisoformat("2026-11-25T23:00:00+09:00")).isoformat() == "2026-10-22"
    with pytest.raises(ValueError, match="verified_schedule_year_unavailable"):
        results._bok_meeting_day(datetime.fromisoformat("2027-01-20T10:00:00+09:00"))


def test_bok_not_posted_yet_stays_missing(transport):
    transport["pages"][results.BOK_MAIN_URL] = BOK_MAIN.replace(b"2026.10.22", b"2026.08.27")
    bok = results.fetch_central_bank_results(NOW)[2]
    assert (bok["status"], bok["reason"], bok["policy_rate"]) == ("missing", "statement_for_meeting_not_posted", None)
    assert bok["scheduled_date"] == "2026-10-22" and bok["source_url"] == results.BOK_MAIN_URL
