import time

from stock_lab_core.prices import _extract_yahoo_overnight_price_from_html


def test_extract_yahoo_overnight_price_from_plain_json_html():
    ts = int(time.time())
    html = (
        '{"symbol":"MRVL","regularMarketPrice":{"raw":310.58},'
        f'"overnightMarketPrice":{{"raw":316.50}},'
        f'"overnightMarketTime":{{"raw":{ts}}}}}'
    )

    assert _extract_yahoo_overnight_price_from_html(html, "MRVL") == 316.50


def test_extract_yahoo_overnight_price_from_escaped_json_html():
    ts = int(time.time())
    html = (
        r'{\"symbol\":\"MRVL\",\"regularMarketPrice\":{\"raw\":310.58},'
        rf'\"overnightMarketPrice\":{{\"raw\":316.50}},'
        rf'\"overnightMarketTime\":{{\"raw\":{ts}}}}}'
    )

    assert _extract_yahoo_overnight_price_from_html(html, "MRVL") == 316.50


def test_extract_yahoo_overnight_price_ignores_stale_quote():
    stale_ts = int(time.time()) - (20 * 60 * 60)
    html = (
        '{"symbol":"MRVL","regularMarketPrice":{"raw":310.58},'
        f'"overnightMarketPrice":{{"raw":316.50}},'
        f'"overnightMarketTime":{{"raw":{stale_ts}}}}}'
    )

    assert _extract_yahoo_overnight_price_from_html(html, "MRVL") == 0.0
