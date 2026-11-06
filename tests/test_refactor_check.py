import pytest

from scripts.check_refactor import (
    BASELINE_FLAGS, ROOT, SCOPES, gate_passes, junit_counts, safe_test_env,
    source_hashes, test_paths as selected_paths,
)


def test_contract_groups_resolve_without_duplicates():
    paths = selected_paths("all")
    assert len(paths) == len(set(paths))
    assert all((ROOT / path).is_file() for path in paths)
    assert set(paths) == {path for scope in SCOPES for path in selected_paths(scope)}


@pytest.mark.parametrize("flag", BASELINE_FLAGS)
def test_verification_cannot_regenerate_baselines(flag):
    with pytest.raises(ValueError, match="regeneration"):
        safe_test_env({flag: "1"})


def test_test_environment_isolated_without_mutating_parent():
    parent = {"PYTEST_ADDOPTS": "-k nonexistent", "STOCK_LAB_FORCE_AUTH_MODE": "private"}
    result = safe_test_env(parent)
    assert "PYTEST_ADDOPTS" not in result
    assert result["STOCK_LAB_FORCE_AUTH_MODE"] == "public_demo"
    assert parent["STOCK_LAB_FORCE_AUTH_MODE"] == "private"


@pytest.mark.parametrize("code,counts,changed", [
    (1, {"tests": 4}, []), (0, {"tests": 0}, []),
    (0, {"tests": 4, "skipped": 1}, []), (0, {"tests": 4, "failures": 1}, []),
    (0, {"tests": 4, "errors": 1}, []), (0, {"tests": 4}, ["tests/golden/x.json"]),
])
def test_incomplete_or_changed_runs_are_blocked(code, counts, changed):
    assert not gate_passes(code, counts, changed)


def test_clean_run_passes():
    assert gate_passes(0, {"tests": 4, "failures": 0, "errors": 0, "skipped": 0}, [])


def test_junit_counts_cases_not_nested_suite_totals(tmp_path):
    path = tmp_path / "junit.xml"
    path.write_text('<testsuites><testsuite><testcase/><testcase><skipped/></testcase>'
                    '<testcase><failure/></testcase><testcase><error/></testcase>'
                    '</testsuite></testsuites>', encoding="utf-8")
    assert junit_counts(path) == dict(tests=4, failures=1, errors=1, skipped=1)


def test_hashes_capture_source_and_fixture_changes_but_not_secrets(tmp_path):
    for name in ("app.py", "tests/golden/x.json", "tests/fixtures/x.json", ".streamlit/secrets.toml"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("first", encoding="utf-8")
    before = source_hashes(tmp_path)
    assert set(before) == {"app.py", "tests/golden/x.json", "tests/fixtures/x.json"}
    (tmp_path / "tests/golden/x.json").write_text("changed", encoding="utf-8")
    assert before != source_hashes(tmp_path)
