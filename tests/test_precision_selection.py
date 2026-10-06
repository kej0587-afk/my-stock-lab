def test_preserve_precision_target_keeps_free_ticker_for_next_rerun(app_module):
    option_map = {
        app_module.FREE_SEARCH_OPTION: {"type": "free"},
        "MSFT": {"type": "preset"},
    }
    for key in [
        app_module.PRECISION_SELECTED_OPTION_KEY,
        app_module.PRECISION_PENDING_SELECTED_OPTION_KEY,
        app_module.PRECISION_PENDING_FREE_TICKER_KEY,
        app_module.PRECISION_PENDING_FREE_MARKET_KEY,
    ]:
        app_module.st.session_state.pop(key, None)

    label = app_module.preserve_precision_target_for_next_rerun("AEHR", option_map)

    assert label == app_module.FREE_SEARCH_OPTION
    assert app_module.st.session_state[app_module.PRECISION_SELECTED_OPTION_KEY] == app_module.FREE_SEARCH_OPTION
    assert app_module.st.session_state[app_module.PRECISION_PENDING_SELECTED_OPTION_KEY] == app_module.FREE_SEARCH_OPTION
    assert app_module.st.session_state[app_module.PRECISION_PENDING_FREE_TICKER_KEY] == "AEHR"
    assert app_module.st.session_state[app_module.PRECISION_PENDING_FREE_MARKET_KEY] == app_module.PRECISION_US_MARKET_OPTION


def test_preserve_precision_target_uses_existing_watchlist_label(app_module):
    option_map = {
        app_module.FREE_SEARCH_OPTION: {"type": "free"},
        "⭐ Microsoft (MSFT)": {
            "type": "watchlist",
            "item": {"ticker": "MSFT", "name": "Microsoft", "is_etf": False, "asset_class": "us_stock"},
        },
    }
    app_module.st.session_state.pop(app_module.PRECISION_SELECTED_OPTION_KEY, None)
    app_module.st.session_state.pop(app_module.PRECISION_PENDING_SELECTED_OPTION_KEY, None)

    label = app_module.preserve_precision_target_for_next_rerun("MSFT", option_map)

    assert label == "⭐ Microsoft (MSFT)"
    assert app_module.st.session_state[app_module.PRECISION_SELECTED_OPTION_KEY] == "⭐ Microsoft (MSFT)"
    assert app_module.st.session_state[app_module.PRECISION_PENDING_SELECTED_OPTION_KEY] == "⭐ Microsoft (MSFT)"
