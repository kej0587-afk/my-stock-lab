# report_sections parity tools

Used for the #19 bounded refactor of `stock_lab_core/report_evidence.report_sections`
(record: `docs/maintenance/20261127_refactor_report_sections_tables.md`). Run in two trees
(the base commit, e.g. a `git worktree`, and the edited tree) and compare.

1. Every `report_sections` call made by the tests (SHA-256 per test and call; `RS_BLOB=1` keeps full text):

       RS_RECORD_OUT=/tmp/before.json PYTHONPATH=scripts/report_sections_parity:. python -X utf8 -m pytest -q -p rs_recorder -p no:cacheprovider tests

   Calls without a fixed `now` print the generation minute (`생성 … KST`), so run both trees
   within the same minute when comparing those tests (market_memo tests).

2. Fixed synthetic inputs (5 times × with/without news), one file per case:

       python -X utf8 -I -c "import sys;sys.path.insert(0,'.');sys.argv=['x','/tmp/out'];exec(open('scripts/report_sections_parity/compare_inputs.py').read())"
       diff -r /tmp/out_before /tmp/out_after
