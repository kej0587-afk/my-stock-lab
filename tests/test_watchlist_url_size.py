import ast
import base64
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace


def sync_function(params, watchlist):
    tree = ast.parse((Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8-sig"))
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                 and node.name in {"encode_watchlist", "sync_watchlist_to_query"}]
    namespace = {"base64": base64, "json": json,
                 "st": SimpleNamespace(query_params=params, session_state=SimpleNamespace(watchlist=watchlist))}
    exec(compile(ast.Module(body=functions, type_ignores=[]), "app.py", "exec"), namespace)
    return namespace["sync_watchlist_to_query"]


def test_small_query_round_trip_and_unrelated_params():
    items = [{"ticker": "MSFT", "name": "Microsoft", "fin_score": 4}]
    params = {"view": "today"}
    sync_function(params, items)()
    assert json.loads(base64.urlsafe_b64decode(params["wl"])) == items
    assert params["view"] == "today"


def test_large_url_copy_removed_without_changing_watchlist():
    items = [{"ticker": f"{index:06d}.KS", "name": "Long registered name", "fin_score": 3}
             for index in range(85)]
    before = deepcopy(items)
    params = {"wl": "old-long-copy", "view": "today"}
    sync_function(params, items)()
    assert params == {"view": "today"}
    assert items == before


def test_large_list_without_existing_url_is_safe():
    items = [{"ticker": "MSFT", "name": "x" * 3000}]
    params = {}
    sync_function(params, items)()
    assert params == {}
