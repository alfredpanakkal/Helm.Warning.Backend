"""Tests for scripts/backfill_issue_dtg.py.

Fake-client unittests only - no live database, no network, no clock reads
(now_utc is injected). Verifies the Phase 2 contract:
fills a trailing DTG; leaves a no-DTG row NULL; skips a future DTG;
skips a range row; never overwrites a non-null valid_from; apply is off
by default; aborts when over --max-updates (writing nothing).
"""

import csv
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from scripts import backfill_issue_dtg as backfill

NOW = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)


def _row(canonical_id, navarea, raw_text, valid_from=None, status="active"):
    return {
        "id": "row-" + navarea + "-" + canonical_id.replace("/", "-"),
        "navarea": navarea,
        "canonical_id": canonical_id,
        "raw_text": raw_text,
        "valid_from": valid_from,
        "status": status,
    }


FILL_ROW = _row(
    "1155/26", "VIII",
    "NAVAREA VIII -1155/26\nVAKALPUDI NAVTEX STATION OFF AIR.\n021102Z/NOV 26")
FILL_VALUE = "2026-11-02T11:02:00"

NO_DTG_ROW = _row(
    "1174/26", "VIII",
    "NAVAREA VIII 1174/26\nMARINE NOTICE TEXT WITHOUT ANY TIME GROUP.")

FUTURE_ROW = _row(
    "001/26", "IX",
    "NAVAREA IX 001/26 GUNNERY EXERCISE.\n131200Z/NOV 26")

CONFLICT_ROW = _row(
    "002/26", "IV",
    "011200Z/NOV 26\nNAVAREA IV 002/26 WORK IN PROGRESS.\n021200Z/NOV 26")

RANGE_ROW = _row(
    "003/26", "IX",
    "NAVAREA IX 003/26 GUNNERY EXERCISE.\n11-11.0N 222-22.0E.\n"
    "14 MAY 27 TO 14 NOV 27")

NON_NULL_ROW = _row(
    "999/26", "VIII",
    "NAVAREA VIII 999/26 ALREADY BACKFILLED.\n021102Z/NOV 26",
    valid_from="2026-10-01T00:00:00")


class _FakeResult:
    def __init__(self, data):
        self.data = data


class _FakeSelect:
    """Applies the same filters the real PostgREST chain sends."""

    def __init__(self, rows):
        self._rows = list(rows)
        self._eq = []
        self._is_null = []
        self._in = {}
        self._range = None

    def select(self, columns):
        return self

    def eq(self, column, value):
        self._eq.append((column, value))
        return self

    def is_(self, column, value):
        self._is_null.append((column, value))
        return self

    def in_(self, column, values):
        self._in[column] = list(values)
        return self

    def range(self, start, end):
        self._range = (start, end)
        return self

    def execute(self):
        rows = self._rows
        for column, value in self._eq:
            rows = [r for r in rows if r.get(column) == value]
        for column, value in self._is_null:
            if value in ("null", None):
                rows = [r for r in rows if r.get(column) is None]
        for column, values in self._in.items():
            rows = [r for r in rows if r.get(column) in values]
        if self._range is not None:
            rows = rows[self._range[0]: self._range[1] + 1]
        return _FakeResult(rows)


class _FakeUpdate:
    """Enforces the apply-time contract: valid_from only, guarded update."""

    def __init__(self, client, payload):
        self._client = client
        self._payload = dict(payload)
        self._filters = []

    def eq(self, column, value):
        self._filters.append(("eq", column, value))
        return self

    def is_(self, column, value):
        self._filters.append(("is", column, value))
        return self

    def execute(self):
        if set(self._payload.keys()) != {"valid_from"}:
            raise AssertionError(
                "update payload must only touch valid_from, got %r"
                % sorted(self._payload.keys()))
        row_id = None
        status_active = False
        null_guard = False
        for kind, column, value in self._filters:
            if kind == "eq" and column == "id":
                row_id = value
            if kind == "eq" and column == "status" and value == "active":
                status_active = True
            if kind == "is" and column == "valid_from":
                null_guard = True
        if row_id is None or not status_active or not null_guard:
            raise AssertionError(
                "update chain must guard on id, status='active' and "
                "valid_from IS NULL")
        matches = [r for r in self._client.rows if r.get("id") == row_id]
        if not matches:
            raise AssertionError("no row with id %r" % row_id)
        row = matches[0]
        if row.get("valid_from") is not None:
            raise AssertionError(
                "refusing to overwrite non-null valid_from for %r"
                % row.get("canonical_id"))
        before = dict(row)
        row["valid_from"] = self._payload["valid_from"]
        self._client.updates.append({
            "id": row_id,
            "canonical_id": row.get("canonical_id"),
            "payload": dict(self._payload),
            "row_before": before,
            "row_after": dict(row),
        })
        return _FakeResult([dict(row)])


class _FakeTable:
    def __init__(self, client):
        self._client = client

    def select(self, columns):
        return _FakeSelect(self._client.rows)

    def update(self, payload):
        return _FakeUpdate(self._client, payload)


class FakeClient:
    def __init__(self, rows):
        self.rows = [dict(r) for r in rows]
        self.updates = []
        self.table_names = []

    def table(self, name):
        self.table_names.append(name)
        return _FakeTable(self)


def _run(client, **kwargs):
    tmp = tempfile.TemporaryDirectory()
    try:
        report = os.path.join(tmp.name, "report.csv")
        before = os.path.join(tmp.name, "before.csv")
        summary = backfill.run_backfill(
            client, NOW, report_path=report, before_path=before,
            log=lambda *_: None, **kwargs)
        report_rows = []
        before_rows = []
        if os.path.exists(report):
            with open(report, newline="", encoding="utf-8") as fh:
                report_rows = list(csv.reader(fh))
        if os.path.exists(before):
            with open(before, newline="", encoding="utf-8") as fh:
                before_rows = list(csv.reader(fh))
        return summary, report_rows, before_rows, report, before
    finally:
        tmp.cleanup()


class ClassifyRowTests(unittest.TestCase):
    def test_fills_trailing_dtg(self):
        outcome, value = backfill.classify_row(FILL_ROW, NOW)
        self.assertEqual(outcome, backfill.OUTCOME_FILLED)
        self.assertEqual(value, FILL_VALUE)

    def test_no_dtg_stays_null_by_rule(self):
        outcome, value = backfill.classify_row(NO_DTG_ROW, NOW)
        self.assertEqual(outcome, backfill.OUTCOME_NULL_BY_RULE)
        self.assertIsNone(value)

    def test_future_dtg_is_skipped(self):
        outcome, value = backfill.classify_row(FUTURE_ROW, NOW)
        self.assertEqual(outcome, backfill.OUTCOME_FUTURE)
        self.assertIsNone(value)

    def test_conflict_dtg_is_skipped(self):
        outcome, value = backfill.classify_row(CONFLICT_ROW, NOW)
        self.assertEqual(outcome, backfill.OUTCOME_CONFLICT)
        self.assertIsNone(value)

    def test_validity_range_row_is_skipped(self):
        outcome, value = backfill.classify_row(RANGE_ROW, NOW)
        self.assertEqual(outcome, backfill.OUTCOME_RANGE)
        self.assertIsNone(value)


class RunBackfillTests(unittest.TestCase):
    def test_apply_is_off_by_default(self):
        client = FakeClient([FILL_ROW, NO_DTG_ROW])
        summary, report_rows, _before, _rp, _bp = _run(client)
        self.assertFalse(summary["apply"])
        self.assertEqual(summary["would_update"], 1)
        self.assertEqual(client.updates, [])
        self.assertEqual(report_rows[0],
                         ["canonical_id", "navarea", "computed_valid_from",
                          "outcome"])
        outcomes = {r[0]: r[3] for r in report_rows[1:]}
        self.assertEqual(outcomes["1155/26"], "filled")
        self.assertEqual(outcomes["1174/26"], "null_by_rule")

    def test_apply_writes_value_and_touches_no_other_column(self):
        client = FakeClient([FILL_ROW, NO_DTG_ROW])
        summary, _report, before_rows, _rp, _bp = _run(client, apply=True)
        self.assertTrue(summary["apply"])
        self.assertEqual(summary["applied"], 1)
        self.assertEqual(summary["failed"], 0)
        self.assertEqual(len(client.updates), 1)
        upd = client.updates[0]
        self.assertEqual(upd["canonical_id"], "1155/26")
        self.assertEqual(upd["payload"], {"valid_from": FILL_VALUE})
        before_keys = set(upd["row_before"].keys()) - {"valid_from"}
        after_keys = set(upd["row_after"].keys()) - {"valid_from"}
        self.assertEqual(before_keys, after_keys)
        for key in before_keys:
            self.assertEqual(upd["row_before"][key], upd["row_after"][key])
        self.assertEqual(client.rows[0]["valid_from"], FILL_VALUE)
        self.assertEqual(client.rows[1]["valid_from"], None)
        self.assertEqual(before_rows[0],
                         ["canonical_id", "id", "valid_from_before",
                          "valid_from_written"])
        self.assertEqual(
            [r[0] for r in before_rows[1:]], ["1155/26"])

    def test_non_null_valid_from_row_is_never_selected_or_updated(self):
        client = FakeClient([FILL_ROW, NON_NULL_ROW])
        summary, report_rows, _before, _rp, _bp = _run(client, apply=True)
        self.assertEqual(summary["fetched"], 1)
        self.assertEqual(summary["applied"], 1)
        self.assertEqual(len(client.updates), 1)
        self.assertNotEqual(client.updates[0]["canonical_id"], "999/26")
        self.assertEqual(client.rows[1]["valid_from"], "2026-10-01T00:00:00")
        ids_in_report = [r[0] for r in report_rows[1:]]
        self.assertNotIn("999/26", ids_in_report)

    def test_apply_time_guard_refuses_non_null_valid_from(self):
        client = FakeClient([NON_NULL_ROW])
        with self.assertRaises(AssertionError):
            backfill.apply_valid_from(
                client, NON_NULL_ROW["id"], "2026-01-01T00:00:00")
        self.assertEqual(client.updates, [])
        self.assertEqual(client.rows[0]["valid_from"],
                         "2026-10-01T00:00:00")

    def test_future_conflict_and_range_rows_are_not_written(self):
        client = FakeClient([FUTURE_ROW, CONFLICT_ROW, RANGE_ROW])
        summary, report_rows, _before, _rp, _bp = _run(client, apply=True)
        self.assertEqual(summary["applied"], 0)
        self.assertEqual(client.updates, [])
        outcomes = {r[0]: r[3] for r in report_rows[1:]}
        self.assertEqual(outcomes["001/26"], "future")
        self.assertEqual(outcomes["002/26"], "conflict")
        self.assertEqual(outcomes["003/26"], "skipped: range")

    def test_abort_over_max_updates_writes_nothing(self):
        rows = [
            _row("010/26", "IV",
                 "NAVAREA IV 010/26 TEST ALPHA.\n011102Z/NOV 26"),
            _row("011/26", "IV",
                 "NAVAREA IV 011/26 TEST BRAVO.\n021102Z/NOV 26"),
            _row("012/26", "IV",
                 "NAVAREA IV 012/26 TEST CHARLIE.\n031102Z/NOV 26"),
        ]
        client = FakeClient(rows)
        summary, report_rows, before_rows, report_path, before_path = _run(
            client, apply=True, max_updates=2)
        self.assertTrue(summary["aborted"])
        self.assertEqual(summary["would_update"], 3)
        self.assertEqual(client.updates, [])
        self.assertEqual(report_rows, [])
        self.assertEqual(before_rows, [])
        for row in client.rows:
            self.assertIsNone(row["valid_from"])


if __name__ == "__main__":
    unittest.main()
