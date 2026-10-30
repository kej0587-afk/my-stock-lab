"""Missing identity must stop at login, never expose the dashboard."""
import ast
from pathlib import Path
from types import SimpleNamespace

import pytest


class Stopped(Exception):
    pass


def run_login(user, allowed):
    tree = ast.parse((Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8-sig"))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "require_login")
    calls = []
    def stop():
        raise Stopped
    streamlit = SimpleNamespace(user=user, title=lambda text: calls.append(text), info=lambda text: calls.append(text),
        button=lambda label, **kwargs: calls.append(label), login=lambda: None, stop=stop,
        error=lambda text: calls.append(text), write=lambda text: calls.append(text))
    namespace = {"st": streamlit, "AUTH_MODE": "google", "is_public_demo_mode": lambda: False,
                 "get_secret_emails": lambda key: set(allowed), "logout_current_user": lambda: None}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "app.py", "exec"), namespace)
    try:
        result = namespace[fn.name]()
    except Stopped:
        result = None
    return result, calls


@pytest.mark.parametrize("user", [SimpleNamespace(), SimpleNamespace(is_logged_in=False)])
def test_unknown_or_signed_out_user_stops_at_login(user):
    result, calls = run_login(user, {"allowed@example.test"})
    assert result is None and "Log in with Google" in calls


def test_logged_in_missing_email_does_not_gain_access():
    result, calls = run_login(SimpleNamespace(is_logged_in=True), {"allowed@example.test"})
    assert result is None and "This Google account is not allowed to use this app." in calls


def test_allowed_email_behavior_is_unchanged():
    result, calls = run_login(SimpleNamespace(is_logged_in=True, email="Allowed@Example.Test"), {"allowed@example.test"})
    assert result == "allowed@example.test" and calls == []
