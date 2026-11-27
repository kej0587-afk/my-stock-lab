"""One public quote snapshot connects cache, precision and report diagnostics."""
import json
from copy import deepcopy
from datetime import datetime, timezone
from unittest.mock import Mock

from stock_lab_core import report_quotes as quotes
from stock_lab_core.leveraged_quote_view import quote_evidence
from stock_lab_core.performance import PerformanceTrace
from stock_lab_core.report_generation_performance import generation_measurement, record_quote_observations
from stock_lab_core.report_intraday import extended_quote_text
from tests.test_leveraged_quote_view import payload


def test_quote_cache_preserves_fetch_clock_and_raw_trade_fields(monkeypatch):
    now, row = payload('GOOGL', '2026-11-13T06:10:00-05:00', 'pre')
    response = Mock(status_code=200)
    response.text = '<script type="application/json">' + json.dumps({
        'status': 200, 'body': json.dumps({'quoteResponse': {'result': [row]}})}) + '</script>'
    get = Mock(return_value=response)
    monkeypatch.setattr(quotes.requests, 'get', get)
    quotes.load_us_report_quote.clear()
    try:
        with PerformanceTrace(scope='quote-cache') as trace:
            first = quotes.load_us_report_quote('GOOGL')
            second = quotes.load_us_report_quote('GOOGL')
        get.assert_called_once()
        assert first == second
        assert first['_retrieved_at'] and first['_http_status'] == 200
        assert first['preMarketTime'] == row['preMarketTime']
        assert first['regularMarketPrice'] == 100
        counts = trace.report()['transport_events']
        assert counts['cache.us_report_quote.miss'] == 1
        assert counts['cache.us_report_quote.reuse'] == 1
    finally:
        quotes.load_us_report_quote.clear()


def test_same_snapshot_precision_report_and_audit_agree_without_mutation():
    now, row = payload('GOOGL', '2026-11-13T06:10:00-05:00', 'pre')
    row.update(_retrieved_at=now.isoformat(), _http_status=200, secret='NOT_EXPORTED')
    before = deepcopy(row)
    evidence = quote_evidence('GOOGL', row, now)
    obs = quotes.extended_quote_observation(row, 'GOOGL', now)
    context = {'sessions': {'US': '2026-11-12'}, 'extended_prices': {'GOOGL': obs}}
    text = extended_quote_text(context, 'GOOGL', now)
    assert '92.87' in text and '-7.13%' in text and '100.00' in text and 'Yahoo' in text
    state = {}
    with generation_measurement(state):
        record_quote_observations({'GOOGL': row}, now)
        state['today_market_memo_text'] = 'report'
    audit = state['auto_report_performance']['quote_observations']['GOOGL']
    assert audit == evidence['audit']
    assert audit['provider_fields']['preMarketPrice'] == evidence['price'] == obs['price']
    assert 'NOT_EXPORTED' not in json.dumps(audit)
    assert row == before
