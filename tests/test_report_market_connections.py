from copy import deepcopy
from datetime import datetime
from pathlib import Path

import pytest

from stock_lab_core.report_market_connections import market_connection_lines

NOW = datetime.fromisoformat("2026-11-04T09:11:00+09:00")


def article(title, key, **changes):
    return dict(title=title, link="https://www.reuters.com/" + key, publisher="Reuters",
                published_at="2026-11-04T07:00:00+09:00", market="US", session_date="2026-11-03", **changes)


def corpus():
    return [article("Device maker warns higher memory costs will pressure margins", "cost"),
            article("Chip supplier reports revenue growth on AI server demand", "demand"),
            article("AI company discloses compute spending commitments and financing risks", "spend")]


def render(news=None, pipeline=None):
    return "\n".join(market_connection_lines({}, pipeline or {}, corpus() if news is None else news, NOW))


def test_source_bound_cross_company_story_without_company_allowlist_or_mutation():
    news = corpus()
    before = deepcopy(news)
    output = render(news)
    assert "AI·반도체 공급망" in output
    assert "공급기업의 판매 기회와 구매기업의 비용 부담" in output
    assert "실제 집행액이나 확보한 자금과 다릅니다" in output
    assert "보도 제목·주장" in output and "연결 해석(가설)" in output
    assert all(item["title"] in output and item["link"] in output for item in news)
    assert "투자 판정·점수에는 반영하지 않습니다" in output
    assert news == before


def test_no_story_from_one_event_or_duplicate_links():
    assert "근거가 부족" in render([corpus()[0]] * 4)
    news = corpus()[:2]
    news[1]["link"] = news[0]["link"]
    assert "근거가 부족" in render(news)


@pytest.mark.parametrize("bad_date", ["2026-11-04T10:00:00+09:00", "2026-10-28T07:00:00+09:00", "invalid"])
def test_future_old_and_undated_material_cannot_form_story(bad_date):
    news = corpus()[:2]
    news[1]["published_at"] = bad_date
    assert "근거가 부족" in render(news)


def packet(**changes):
    result = dict(official=True, date="2026-11-03", ticker="FIXTURE", name="Example Manufacturer",
        sector="반도체", market="US", fiscal_period="FY2027Q1", event={},
        metrics={"guidance": {"status": "reported", "text": "Memory revenue outlook is $12 billion; not actual revenue.",
                              "source_url": "https://example.com/ir/results"}})
    result.update(changes)
    return result


def test_official_forecast_is_not_actual_or_consensus_and_preserves_units():
    pipeline = {"packets": [packet()]}
    before = deepcopy(pipeline)
    output = render([corpus()[0]], pipeline)
    assert "회사 전망·실제치 아님" in output
    assert r"\$12 billion; not actual revenue." in output
    assert "FY2027Q1" in output
    assert "예상치 상회" not in output
    assert before == pipeline


@pytest.mark.parametrize("changes", [{"official": False}, {"event": {"result_stale": True}}, {"date": "2026-11-05"}])
def test_unconfirmed_stale_future_official_results_are_excluded(changes):
    assert "근거가 부족" in render([corpus()[0]], {"packets": [packet(**changes)]})


def test_metrics_from_one_release_cannot_count_as_two_announcements():
    p = packet()
    p["metrics"]["capex"] = dict(status="reported", text="AI capex is $5 billion.", source_url="https://example.com/ir/capex")
    assert "근거가 부족" in render([], {"packets": [p]})


def test_untrusted_source_and_missing_url_are_not_evidence():
    news = corpus()[:2]
    news[1].update(publisher="unknown", link="https://spam.invalid/story")
    assert "근거가 부족" in render(news)
    news[1]["link"] = ""
    assert "근거가 부족" in render(news)


def test_other_industries_and_conflicting_headlines_do_not_infer_direction():
    news = [article("Oil prices fall and airline fuel costs ease", "oil"),
            article("Energy company raises revenue guidance", "energy")]
    output = render(news)
    assert "에너지·운송" in output
    assert "Oil prices fall" in output
    assert "유가 상승" not in output


def test_report_generation_calls_connection_module():
    source = (Path(__file__).parents[1] / "stock_lab_core" / "report_evidence.py").read_text(encoding="utf-8")
    assert "lines.extend(market_connection_lines(context, earnings_pipeline, news, now))" in source
    from stock_lab_core.report_build import get_report_build_info
    source_info = get_report_build_info()["sources"]["stock_lab_core.report_market_connections"]
    assert source_info["sha256"] == source_info["disk_sha256"]
