#!/usr/bin/env python3
"""
Tests for validation_progress.py — the self-validation readiness watcher.

Runs the real script against temp tracker/recommendations/state files via
its env-var configuration. No network, no production files touched.

Run:  python3 tests/test_validation_progress.py
"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock
from datetime import datetime

import pytz

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))

import validation_progress as vp  # noqa: E402

TODAY = datetime.now(pytz.timezone("America/Edmonton")).strftime("%Y-%m-%d")

HEADER = ("| Signal Date | Ticker | Setup | Rank | Entry Price | RSI | Vol Ratio | "
          "Divergence | PEAD | Insider | 200SMA_Near | T+2 | T+5 | T+10 | Outcome | Catalyst |\n"
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|\n")


class WatcherHarness(unittest.TestCase):
    """Wires the module's path constants into per-test temp files."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="astp_vp_")
        self.tracker = os.path.join(self.tmp, "SignalTracker.md")
        self.recs = os.path.join(self.tmp, "recs.json")
        self.state = os.path.join(self.tmp, "state.json")
        with open(self.tracker, "w") as f:
            f.write(HEADER)
        with open(self.recs, "w") as f:
            json.dump({"changes": [
                {"date": "2026-08-25", "description": "RSI 65 to 55",
                 "filter": "rsi_lt_55", "expected_impact": "-"}]}, f)
        for attr, val in (("TRACKER", self.tracker), ("RECS", self.recs),
                          ("STATE", self.state)):
            p = mock.patch.object(vp, attr, val)
            p.start()
            self.addCleanup(p.stop)

    def _signal(self, date, ticker, outcome=""):
        with open(self.tracker, "a") as f:
            f.write(f"| {date} | {ticker} | BUY_A | 1 | $10.00 | 30.00 | 1.00x | "
                    f"No | N | N | N | | | | {outcome} | |\n")

    def _run(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            vp.main()
        return buf.getvalue()


class TestWatcher(WatcherHarness):
    def test_baseline_prints_then_silent(self):
        self._signal("2026-08-26", "AAAA")
        first = self._run()
        self.assertIn("baseline established", first)
        self.assertIn("1 logged", first)
        second = self._run()
        self.assertEqual(second, "", "silent run printed output")

    def test_new_signal_reprints(self):
        self._signal("2026-08-26", "AAAA")
        self._run()
        self._signal("2026-08-27", "BBBB")
        out = self._run()
        self.assertIn("2 logged", out)

    def test_completion_counts_and_progress(self):
        self._signal("2026-08-26", "AAAA", outcome="WIN (+3.00%)")
        out = self._run()
        self.assertIn("1/15 completed", out)

    def test_validation_ready_milestone(self):
        for i in range(15):
            self._signal("2026-08-26", f"T{i:02d}", outcome="LOSS (-1.00%)")
        out = self._run()
        self.assertIn("VALIDATION READY", out)

    def test_missing_inputs_exit_nonzero(self):
        with mock.patch.object(vp, "RECS", os.path.join(self.tmp, "nope.json")):
            with self.assertRaises(SystemExit) as cm:
                self._run()
        self.assertEqual(cm.exception.code, 1)
        with mock.patch.object(vp, "TRACKER", os.path.join(self.tmp, "nope.md")):
            with self.assertRaises(SystemExit) as cm:
                self._run()
        self.assertEqual(cm.exception.code, 1)

    def test_stagnation_alert(self):
        # A signal dated exactly on the change date (2026-08-25) is 3
        # business days old relative to the real "today" (2026-08-28),
        # which crosses the 3-day stagnation threshold.
        self._signal("2026-08-25", "AAAA")
        out = self._run()
        self.assertIn("STAGNATION ALERT", out)


class TestBusinessDayMath(unittest.TestCase):
    def test_busday_count_matches_known_values(self):
        # Fri 2026-08-28 -> Tue 2026-09-01: counts Fri + Mon = 2
        self.assertEqual(vp.busday_count("2026-08-28", "2026-09-01"), 2)
        # same day -> 0
        self.assertEqual(vp.busday_count("2026-08-28", "2026-08-28"), 0)
        # a full week Mon->Mon = 5
        self.assertEqual(vp.busday_count("2026-08-24", "2026-08-31"), 5)
        # reversed -> 0
        self.assertEqual(vp.busday_count("2026-09-01", "2026-08-28"), 0)

    def test_busday_offset_rolls_weekends(self):
        # Sat 2026-08-29 rolls to Mon, +0 business days
        self.assertEqual(vp.busday_offset("2026-08-29", 0), "2026-08-31")
        # Fri 2026-08-28 + 10 business days = Fri 2026-09-11
        self.assertEqual(vp.busday_offset("2026-08-28", 10), "2026-09-11")
        # Fri + 1 = Mon
        self.assertEqual(vp.busday_offset("2026-08-28", 1), "2026-08-31")


if __name__ == "__main__":
    unittest.main(verbosity=2)
