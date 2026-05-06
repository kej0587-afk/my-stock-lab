"""Shared constants and column schemas for Stock Lab.

Keep this module free of Streamlit/Supabase runtime code. It is the first
staging area for constants that used to live directly in app.py.
"""

RESERVE_TICKERS = {"357870", "sgov"}
RESERVE_BUCKETS = {"reserve", "cash"}

DEFAULT_WATCHLIST = [
    {"name": "MSFT", "ticker": "MSFT", "is_etf": False, "asset_class": "us_stock"},
    {"name": "QQQM", "ticker": "QQQM", "is_etf": True, "asset_class": "us_etf_nasdaq"},
    {"name": "TQQQ", "ticker": "TQQQ", "is_etf": True, "asset_class": "us_etf_nasdaq"},
    {"name": "하이닉스", "ticker": "000660.KS", "is_etf": False, "asset_class": "kr_stock"},
    {"name": "두산에너빌리티", "ticker": "034020.KS", "is_etf": False, "asset_class": "kr_stock"},
]

SETTINGS_COLUMNS = ["seed_money", "krw_cash", "usd_cash", "usdkrw", "reserve_target_weight"]
HOLDINGS_COLUMNS = ["ticker", "name", "qty", "avg_price", "target_weight", "asset_class", "is_etf", "bucket"]
DIVIDENDS_COLUMNS = ["id", "date", "ticker", "amount", "currency"]
MONTHLY_LOG_COLUMNS = ["month", "total_invested", "evaluated_value", "dividend"]
FIN_SCORE_COLUMNS = ["ticker", "auto_score", "manual_score", "final_score", "source", "notes_json"]
WATCHLIST_COLUMNS = ["name", "ticker", "is_etf", "asset_class", "fin_score"]

SWING_RADAR_COLUMNS = [
    "ticker", "name", "asset_class", "idea",
    "check_1", "check_2", "check_3",
    "risk_1", "risk_2", "risk_3",
    "entry_rule", "exit_rule", "next_event",
    "status", "decision", "importance",
    "reference_link", "last_checked", "memo",
]

SWING_EDITOR_COLUMNS = [
    "status", "decision", "importance",
    "name", "ticker", "asset_class",
    "idea", "check_1", "check_2", "check_3",
    "risk_1", "risk_2", "risk_3",
    "entry_rule", "exit_rule", "next_event",
    "last_checked", "reference_link", "memo",
]

SWING_TEMPLATE_TEXT_FIELDS = [
    "idea", "check_1", "check_2", "check_3",
    "risk_1", "risk_2", "risk_3",
    "entry_rule", "exit_rule", "next_event",
]
