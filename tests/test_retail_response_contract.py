"""Offline regression coverage for the Census retail response contract."""

from copy import deepcopy
from datetime import datetime, timezone
import unittest
from unittest.mock import patch

from stock_lab_core import economic_releases as releases


NOW = datetime(2026, 10, 21, 11, tzinfo=timezone.utc)
FILTERS = {
    "category_code": "44X72", "data_type_code": "MPCSM",
    "seasonally_adj": "yes", "error_data": "no",
}
HEADER = ["cell_value", "time_slot_date", "time", *FILTERS]
HISTORY = [
    {"period": "2025-01", "value": -0.7},
    {"period": "2025-02", "value": -0.5},
]


class RetailResponseContractTests(unittest.TestCase):
    def setUp(self):
        releases.clear_economic_releases_cache()
        self.addCleanup(releases.clear_economic_releases_cache)
        state = self.server = {
            "rows": [
                {"cell_value": "-0.7", "time_slot_date": "2025-01-01 00:00:00.0",
                 "time": "2025-01", **FILTERS},
                {"cell_value": "-0.5", "time_slot_date": "2025-02-01 00:00:00.0",
                 "time": "2025-02", **FILTERS},
            ],
            "header": None, "payload": None, "calls": [], "closed": 0,
        }

        def forbidden(*args, **kwargs):
            self.fail("Network and credential access are forbidden in retail tests")

        class Response:
            status_code = 200

            def __init__(self, payload):
                self.payload = payload

            def json(self):
                return deepcopy(self.payload)

            def close(self):
                state["closed"] += 1

        def get(url, **kwargs):
            self.assertEqual(url, releases.CENSUS_URL)
            params = kwargs["params"]
            self.assertNotIn("key", params)
            self.assertIs(kwargs["allow_redirects"], False)
            state["calls"].append(deepcopy(params))
            header = state["header"]
            if header is None:
                # Census appends the time and predicate columns to requested fields.
                header = params["get"].split(",") + ["time", *FILTERS]
            payload = state["payload"]
            if payload is None:
                payload = [header] + [[row[field] for field in header] for row in state["rows"]]
            return Response(payload)

        self.enterContext(patch.object(releases, "_api_key", forbidden))
        self.enterContext(patch.object(releases.requests.sessions.Session, "request", forbidden))
        self.enterContext(patch.object(releases.requests, "get", get))
        self.enterContext(patch.object(releases.requests, "post", forbidden))

    def test_report_samples_follow_normal_server_response_contract(self):
        row = releases._retail(NOW, "")

        params = self.server["calls"][0]
        self.assertEqual(params["get"], "cell_value,time_slot_date")
        self.assertFalse(set(params["get"].split(",")) & FILTERS.keys())
        self.assertTrue(all(params[field] == value for field, value in FILTERS.items()))
        self.assertEqual((row["actual"], row["previous"]), (-0.5, -0.7))
        self.assertEqual(row["period"], "2025-02")
        self.assertEqual(row["history"], HISTORY)
        metadata = row["request_metadata"]
        self.assertEqual(metadata["http_status"], 200)
        self.assertEqual(metadata["response_status"], "observations_validated")
        self.assertEqual(metadata["response_summary"]["columns"], HEADER)
        self.assertEqual(metadata["observation_count"], 2)
        self.assertEqual(metadata["rejected_rows"], {})
        self.assertIs(metadata["from_cache"], False)
        self.assertEqual(self.server["closed"], 1)

    def test_unparseable_time_slot_date_falls_back_to_time(self):
        self.server["header"] = HEADER
        for invalid_date in ("2025-01-01 00:00:00.0", "invalid-date"):
            with self.subTest(invalid_date=invalid_date):
                releases.clear_economic_releases_cache()
                self.server["rows"][0]["time_slot_date"] = invalid_date
                row = releases._retail(NOW, "")
                self.assertEqual(row["history"], HISTORY)
                self.assertEqual(row["request_metadata"]["rejected_rows"], {})

    def test_parseable_time_slot_date_keeps_precedence(self):
        for item in self.server["rows"]:
            item["time_slot_date"] = item["time"] + "-01"
            item["time"] = "2026-09"

        self.assertEqual(releases._retail(NOW, "")["history"], HISTORY)

    def test_date_only_response_without_time_remains_supported(self):
        self.server["header"] = [field for field in HEADER if field != "time"]
        for item in self.server["rows"]:
            item["time_slot_date"] = item["time"] + "-01"

        self.assertEqual(releases._retail(NOW, "")["history"], HISTORY)

    def test_invalid_rows_are_rejected_by_reason(self):
        cases = [
            ({"time": "2026-10"}, "outside_completed_range"),
            ({"time": "2026-11"}, "outside_completed_range"),
            ({"cell_value": "not-a-number"}, "invalid_value"),
            ({"cell_value": "."}, "invalid_value"),
            ({"cell_value": ""}, "invalid_value"),
            ({"cell_value": None}, "invalid_value"),
            ({"cell_value": "NaN"}, "invalid_value"),
            ({"cell_value": "Infinity"}, "invalid_value"),
            ({"category_code": "44000"}, "category_mismatch"),
            ({"data_type_code": "SM"}, "data_type_mismatch"),
            ({"seasonally_adj": "no"}, "adjustment_mismatch"),
            ({"error_data": "yes"}, "error_data"),
            ({"time_slot_date": "invalid", "time": "invalid"}, "invalid_period"),
        ]
        samples = deepcopy(self.server["rows"])
        for changes, reason in cases:
            with self.subTest(changes=changes, reason=reason):
                releases.clear_economic_releases_cache()
                self.server["rows"] = samples + [{**samples[-1], **changes}]
                row = releases._retail(NOW, "")
                self.assertEqual(row["history"], HISTORY)
                self.assertEqual((row["actual"], row["previous"]), (-0.5, -0.7))
                self.assertEqual(row["request_metadata"]["observation_count"], 2)
                self.assertEqual(row["request_metadata"]["rejected_rows"], {reason: 1})

    def test_conflicting_duplicate_columns_are_rejected(self):
        for field, conflicting in (
            ("category_code", "44000"), ("cell_value", "999"), ("time", "2026-09"),
        ):
            with self.subTest(field=field):
                releases.clear_economic_releases_cache()
                sample = self.server["rows"][0]
                self.server["payload"] = [
                    HEADER + [field], [sample[name] for name in HEADER] + [conflicting],
                ]
                row = releases._retail(NOW, "")
                self.assertIsNone(row["actual"])
                self.assertEqual(row["history"], [])
                self.assertEqual(row["status"], "unavailable")
                self.assertIn("census_invalid_columns", row["missing_reason"])
                self.assertEqual(row["request_metadata"]["http_status"], 200)

    def test_no_valid_rows_remains_unconfirmed_and_is_not_cached(self):
        self.server["rows"] = [{**self.server["rows"][0], "cell_value": "."}]

        for _ in range(2):
            row = releases._retail(NOW, "")
            self.assertIsNone(row["actual"])
            self.assertEqual(row["history"], [])
            self.assertEqual(row["publication_status"], "unconfirmed")
            self.assertIn("census_no_valid_observations", row["missing_reason"])
            self.assertEqual(row["request_metadata"]["rejected_rows"], {"invalid_value": 1})

        self.assertEqual(len(self.server["calls"]), 2)
