"""Collect/validate local raw DART evidence; never import the app or write scores."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import tomllib

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from stock_lab_core.dart_corporate_codes import fetch_corporate_codes
from stock_lab_core.dart_evidence import EvidenceError, read_bundle, require, validate_scope, write_bundle
from stock_lab_core.dart_evidence_collector import collect_evidence


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    collect = commands.add_parser("collect")
    collect.add_argument("--ticker", required=True)
    collect.add_argument("--report", action="append", required=True, metavar="YEAR:CODE")
    collect.add_argument("--secrets-file", type=Path)
    collect.add_argument("--output", type=Path)
    validate = commands.add_parser("validate")
    validate.add_argument("file", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            _, summary = read_bundle(args.file)
            print(json.dumps(summary))  # Offline validation does not authenticate source/identity.
            return 0
        scope = []
        for spec in args.report:
            parts = spec.split(":")
            require(len(parts) == 2, "invalid_report_argument")
            scope.append({"year": parts[0], "report_code": parts[1]})
        validate_scope(scope)
        destination = ROOT / "cache" / "financial_evidence"
        output = args.output or destination / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".json")
        output = output.resolve()
        require(output.is_relative_to(destination.resolve()), "output_must_be_private_cache")
        require(not output.exists(), "output_exists")
        key = os.environ.get("DART_API_KEY", "")
        if not key and args.secrets_file:
            settings = tomllib.loads(args.secrets_file.read_text(encoding="utf-8-sig"))
            key = settings.get("dart_api_key") or settings.get("DART_API_KEY") or ""
        require(isinstance(key, str) and bool(key), "missing_key")
        codes = fetch_corporate_codes(key, get=lambda url, **kw: requests.get(url, allow_redirects=False, **kw))
        require(bool(codes), "official_identity_lookup_failed")
        payload = collect_evidence(args.ticker, scope, key, codes)
        summary = write_bundle(output, payload, corporate_codes=codes)
        print(json.dumps({"file": str(output), **summary}))
        return 0 if summary["complete"] and summary["report_count"] else 2
    except EvidenceError as error:
        print(json.dumps({"error": str(error)}))
        return 1
    except (OSError, ValueError, TypeError):
        print(json.dumps({"error": "local_input_or_file_error"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
