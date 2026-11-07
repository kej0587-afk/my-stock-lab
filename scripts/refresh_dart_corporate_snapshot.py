"""Refresh public identifiers only. Credentials never appear in the output file."""

import argparse
from datetime import datetime, timezone
import json
import os
import re
from pathlib import Path
import sys
import tomllib

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from stock_lab_core.dart_corporate_codes import fetch_corporate_codes
from stock_lab_core.dart_corporate_snapshot import SNAPSHOT_PATH, SOURCE


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--secrets-file", type=Path)
    parser.add_argument("--output", type=Path, default=SNAPSHOT_PATH)
    args = parser.parse_args()
    key = os.environ.get("DART_API_KEY", "")
    if not key and args.secrets_file:
        settings = tomllib.loads(args.secrets_file.read_text(encoding="utf-8-sig"))
        key = settings.get("dart_api_key") or settings.get("DART_API_KEY") or ""
    result = fetch_corporate_codes(key)
    if not result:
        print(json.dumps(result.diagnostic))
        return 1
    if any(not re.fullmatch(r"[0-9A-Z]{6}", stock) or not corp.isdigit() or len(corp) != 8
           for stock, corp in result.items()):
        print("Unexpected identifier format; snapshot was not changed.")
        return 1
    payload = {"version": 1, "source": SOURCE, "retrieved_at": datetime.now(timezone.utc).isoformat(),
               "codes": dict(sorted(result.items()))}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"mapped_count": len(result), "diagnostic": result.diagnostic}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
