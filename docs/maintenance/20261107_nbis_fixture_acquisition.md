# NBIS official fixture acquisition: incomplete

2026-11-07 KST. Clean `main`, base `554cafd1`, matching origin after fetch.
Scope: obtain official input before implementing the separate annual review parser.

## Results

- One direct request to the original SEC20-F returned HTTP403, text/html,4819bytes,
  at11:03:32 UTC. The failure body was not saved as financial data. Safe request
  metadata is in ignored `cache/nbis_official_fetch.json`. No header rotation,
  fabricated contact or alternate mirror used to bypass the response.
- Local secrets file exists; effective local `sec_user_agent` is absent. Only
  presence was printed. This does not prove why SEC returned403 or establish the
  production configuration. Asked user to configure their actual contact locally;
  configuration does not guarantee a successful subsequent request.
- Research tool can read official SEC report text. That is source evidence, not
  downloaded raw companyfacts/iXBRL for validating tags, units and contexts.
- Inspected [issuer financials](https://nebius.com/financials) and
  [investor hub](https://nebius.com/investor-hub). Available earnings-release links
  were not substituted for a20-F machine-readable fixture.

## Amendment finding

[SEC amendment index](https://www.sec.gov/Archives/edgar/data/1513845/000110465926065681/0001104659-26-065681-index.htm)
identifies a20-F/A filed2026-05-22 for period2025-12-31.
[Its explanatory note](https://www.sec.gov/Archives/edgar/data/1513845/000110465926065681/nbis-20251231x20fa.htm)
says its purpose is adding Exhibit97.1; other original disclosures are unchanged.
The financial source remains the
[original20-F filed2026-04-30](https://www.sec.gov/Archives/edgar/data/1513845/000110465926052948/nbis-20251231x20f.htm).

Future acceptance test: an exhibit-only amendment must not remove valid earlier
financial facts. Preserve each financial field's actual accession/period; do not
label original figures as newly reported or restated merely because an amendment
is newer. This requirement is verified from the explanatory note, not from an
unobtained companyfacts payload.

## Preservation and next action

No parser, UI, provider or scoring files changed. No DB writes, automatic score
refresh, API key changes or investment-decision changes. No synthetic fixture
presented as real financial evidence. No runtime tests repeated for docs-only work;
the prior57-test result remains historical, not a new run.

After user configuration or a legitimate supplied official file, acquire and
validate a dated source fixture, then implement the isolated review-only annual
reader specified in HANDOFF. SEC403 may persist; report any remaining transport
limit explicitly. Parser implementation and fixture-based acceptance are unfinished.
Documentation-only publication requires no app reboot.
