# CLAUDE.md

Short pointer file. The full agent guide is [AGENTS.md](AGENTS.md); the current task and history are in
[HANDOFF.md](HANDOFF.md) (read its **Next Task Only** first) and
[docs/maintenance/ROADMAP.md](docs/maintenance/ROADMAP.md).

- Do not change trading scores, weights, gates or buy conditions unless the user asks.
- Never invent numbers; missing data stays 미연결/미확인, never 0 or an estimate.
- Before and after a change, run `python scripts/check_refactor.py --scope report` (or `decision`, `prices`, `all`).
  Some tests fail on `main` already; HANDOFF lists them. Compare failures before/after instead of assuming.
- Compare speed only under the condition in `docs/maintenance/20261124_performance_baseline.md`.
- Production is Streamlit Cloud deployed from `main`; after a merge, reboot and check one real report before
  calling a change verified. Record the check (time in KST) in the task's doc and HANDOFF.
- Keep private account data, reports and secrets out of Git.
