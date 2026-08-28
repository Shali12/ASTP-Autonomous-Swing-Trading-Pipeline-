#!/usr/bin/env python3
"""
Regression tests for the trading pipeline scripts.

Covers:
  - health_check.py  signal regex tolerates flagged headers, audit headers
                     excluded, deterministic LLM-fail override, silent-cron
                     behaviour for clean tracker/summary runs
  - tracker.py       10-day same-ticker dedupe, new-ticker logging,
                     invalid-price rejection
  - daily_premarket_report.py  one retry on Gemini 5xx, graceful degradation,
                     N/A fallback on market-data failure, report layout

All tests are hermetic: temp files only, network/Telegram mocked via
unittest.mock. No real API calls, no real files touched.

Run:  python3 tests/test_health_fixes.py
"""
import os
import sys
import tempfile
import unittest
from io import StringIO
from unittest import mock
from datetime import datetime

import pytz

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))

import health_check as hc            # noqa: E402
import tracker as tracker_mod        # noqa: E402
import daily_premarket_report as dr  # noqa: E402

TODAY = datetime.now(pytz.timezone("America/Edmonton")).strftime("%Y-%m-%d")

SAMPLE_BRIEF = (
    "# Daily Trading Brief - 2026-08-28\n"
    "### CPRI - BUY_A\n- **Current Price**: $13.42\n- **RSI (14)**: 31.06\n"
    "### AAON \U0001F6A9 Catalyst - BUY_A\n- **RSI (14)**: 32.00\n"
    "### GME \u26A0\uFE0F Supply Warning - BUY_A\n"
    "### PYPL - WATCH_B\n### ACGL - WATCH_B\n"
    "### \U0001F4CA Technical Audit for GME\n"
)


class TempDirsMixin:
    """Per-test temp dirs wired into the env-configurable module constants."""

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp(prefix="astp_test_")
        self.logs = os.path.join(self.tmp, "logs")
        self.briefs = os.path.join(self.tmp, "briefs")
        os.makedirs(self.logs)
        os.makedirs(self.briefs)
        self.tracker_path = os.path.join(self.tmp, "SignalTracker.md")
        self._patches = [
            mock.patch.object(hc, "LOG_DIR", self.logs),
            mock.patch.object(hc, "BRIEF_DIR", self.briefs),
            mock.patch.object(hc, "TRACKER_FILE", self.tracker_path),
        ]
        for p in self._patches:
            p.start()
            self.addCleanup(p.stop)


class TestSignalRegex(unittest.TestCase):
    NEW_A = r'^### \S+.*? - BUY_A$'
    NEW_SIGS = r'^### (\S+).*? - (?:BUY_A|BUY_B)$'
    OLD = r'^### \S+ - (?:BUY_A|BUY_B)'  # pre-fix pattern, kept as characterization

    def test_counts_flagged_headers(self):
        self.assertEqual(len(re.findall(self.NEW_A, SAMPLE_BRIEF, re.M)), 3)

    def test_audit_headers_never_counted(self):
        sigs = re.findall(self.NEW_SIGS, SAMPLE_BRIEF, re.M)
        self.assertNotIn("Technical", sigs)
        self.assertEqual(len(sigs), 3)

    def test_watch_b_is_not_a_signal(self):
        sigs = re.findall(self.NEW_SIGS, SAMPLE_BRIEF, re.M)
        self.assertNotIn("PYPL", sigs)
        self.assertNotIn("ACGL", sigs)

    def test_old_regex_undercounted(self):
        """Documents the pre-fix bug: old pattern found 1 of 3 signals."""
        self.assertEqual(len(re.findall(self.OLD, SAMPLE_BRIEF, re.M)), 1)

    def test_duplicates_detected(self):
        issues = hc.deterministic_issues(SAMPLE_BRIEF + "### AAON \U0001F6A9 Catalyst - BUY_A\n")
        self.assertTrue(any("duplicate" in i for i in issues))

    def test_clean_sample_no_issues(self):
        self.assertEqual(hc.deterministic_issues(SAMPLE_BRIEF), [])

    def test_rsi_guard_unchanged(self):
        bad = "### X - BUY_A\n- **RSI (14)**: 150.00\n"
        self.assertTrue(any("RSI out of range" in i for i in hc.deterministic_issues(bad)))

    def test_price_guard_unchanged(self):
        bad = "### X - BUY_A\n- **Current Price**: $0.00\n"
        self.assertTrue(any("Price non-positive" in i for i in hc.deterministic_issues(bad)))


import re  # noqa: E402  (used above; kept late so the class reads first)


class TestCheckBrief(TempDirsMixin, unittest.TestCase):
    def _write_brief(self):
        with open(os.path.join(self.briefs, f"{TODAY}.md"), "w") as f:
            f.write(SAMPLE_BRIEF)

    def _write_exit(self, val):
        with open(os.path.join(self.logs, "brief_last.exit"), "w") as f:
            f.write(val)

    def test_reports_flagged_signals_no_manual_check(self):
        self._write_brief()
        self._write_exit("0")
        with open(self.tracker_path, "w") as f:
            f.write(f"| {TODAY} | CPRI | ...\n")
        captured = {}
        with mock.patch.object(hc, "send_telegram",
                               side_effect=lambda m: captured.update(msg=m)), \
             mock.patch.object(hc, "llm_quality_check",
                               return_value={"status": "PASS", "reason": "stub"}):
            hc.check_brief()
        msg = captured["msg"]
        self.assertIn("BUY_A: 3", msg)
        self.assertIn("Exit: \u2705 OK", msg)
        self.assertNotIn("Manual check required", msg)

    def test_llm_fail_overridden_when_deterministics_clean(self):
        self._write_brief()
        self._write_exit("0")
        with open(self.tracker_path, "w") as f:
            f.write(f"| {TODAY} | CPRI | ...\n")
        captured = {}
        with mock.patch.object(hc, "send_telegram",
                               side_effect=lambda m: captured.update(msg=m)), \
             mock.patch.object(hc, "llm_quality_check",
                               return_value={"status": "FAIL", "reason": "stub"}):
            hc.check_brief()
        self.assertIn("PASS", captured["msg"])

    def test_missing_file_fails(self):
        self._write_exit("0")
        captured = {}
        with mock.patch.object(hc, "send_telegram",
                               side_effect=lambda m: captured.update(msg=m)), \
             mock.patch.object(hc, "llm_quality_check",
                               return_value={"status": "UNKNOWN", "reason": "-"}):
            hc.check_brief()
        self.assertIn("Manual check required", captured["msg"])
        self.assertIn("File: \u274c Missing", captured["msg"])


class TestSilentCron(TempDirsMixin, unittest.TestCase):
    def _tracker_today(self):
        header = ("| Signal Date | Ticker | Setup | Rank | Entry Price | RSI | Vol Ratio | "
                  "Divergence | PEAD | Insider | 200SMA_Near | T+2 | T+5 | T+10 | Outcome | Catalyst |\n"
                  "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|\n")
        with open(self.tracker_path, "w") as f:
            f.write(header + f"| {TODAY} | CPRI | BUY_A | 1 | $13.42 | 31.06 | 0.08x | No | N | N | N | +1.0% | +2.0% | +3.0% | WIN (+3.00%) | |\n")

    def test_clean_tracker_run_sends_nothing(self):
        self._tracker_today()
        with open(os.path.join(self.logs, "tracker_last.exit"), "w") as f:
            f.write("0")
        with mock.patch.object(hc, "send_telegram") as send:
            hc.check_tracker()
        send.assert_not_called()

    def test_stale_tracker_alerts(self):
        self._tracker_today()
        with open(os.path.join(self.logs, "tracker_last.exit"), "w") as f:
            f.write("0")
        captured = {}
        with mock.patch.object(hc, "send_telegram",
                               side_effect=lambda m: captured.update(msg=m)):
            # simulate staleness: file mtime 60 min ago
            old = __import__("time").time() - 3600
            os.utime(self.tracker_path, (old, old))
            hc.check_tracker()
        self.assertIn("Manual check required", captured["msg"])


class TestTrackerDedupe(unittest.TestCase):
    HEADER = ("| Signal Date | Ticker | Setup | Rank | Entry Price | RSI | Vol Ratio | "
              "Divergence | PEAD | Insider | 200SMA_Near | T+2 | T+5 | T+10 | Outcome | Catalyst |\n"
              "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|\n")

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="astp_tracker_")
        self.tracker_path = os.path.join(self.tmp, "SignalTracker.md")
        with open(self.tracker_path, "w") as f:
            f.write(self.HEADER + f"| {TODAY} | CPRI | BUY_A | 1 | $13.42 | 31.06 | 0.08x | No | N | N | N | | | | | |\n")
        patcher = mock.patch.object(tracker_mod, "TRACKER_FILE", self.tracker_path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _rows(self, needle):
        with open(self.tracker_path) as f:
            return [l for l in f if needle in l and not l.startswith("|--")]

    def test_same_ticker_same_day_skipped(self):
        out = StringIO()
        with mock.patch("sys.stdout", out):
            tracker_mod.log_signal("CPRI", "BUY_A", 1, 13.42, 31.06, 0.08, False)
        self.assertEqual(len(self._rows(f"| {TODAY} | CPRI |")), 1, "duplicate written!")

    def test_new_ticker_logged(self):
        out = StringIO()
        with mock.patch("sys.stdout", out):
            tracker_mod.log_signal("ZZZZ", "BUY_B", 1, 50.0, 45.0, 1.7, False)
        self.assertEqual(len(self._rows("| ZZZZ |")), 1)

    def test_invalid_price_rejected(self):
        out = StringIO()
        with mock.patch("sys.stdout", out):
            tracker_mod.log_signal("YYYY", "BUY_A", 1, 0.0, 30.0, 1.0, False)
        self.assertEqual(len(self._rows("| YYYY |")), 0)


class TestPremarketRetry(unittest.TestCase):
    def _resp(self, status=200):
        resp = mock.Mock()
        if status >= 500:
            import requests
            resp.raise_for_status.side_effect = requests.exceptions.HTTPError(f"{status}")
        else:
            resp.raise_for_status.return_value = None
            resp.json.return_value = {"candidates": [{"content": {
                "parts": [{"text": '{"sentiment": "BULLISH", "reasoning": "test"}'}]}}]}
        return resp

    def setUp(self):
        self.key_old = os.environ.get("GEMINI_API_KEY")
        os.environ["GEMINI_API_KEY"] = "dummy"
        patcher = mock.patch.object(dr, "get_macro_headlines",
                                    return_value=["Fed signals rate cut"])
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        if self.key_old is not None:
            os.environ["GEMINI_API_KEY"] = self.key_old

    @mock.patch("time.sleep", return_value=None)
    def test_503_then_success_recovers(self, _s):
        with mock.patch("requests.post",
                        side_effect=[self._resp(503), self._resp(200)]) as post:
            self.assertEqual(dr.get_macro_sentiment(), "BULLISH - test")
        self.assertEqual(post.call_count, 2)

    @mock.patch("time.sleep", return_value=None)
    def test_persistent_503_degrades_gracefully(self, _s):
        with mock.patch("requests.post",
                        side_effect=[self._resp(503), self._resp(503)]) as post:
            self.assertEqual(dr.get_macro_sentiment(), "Sentiment data unavailable")
        self.assertEqual(post.call_count, 2, "expected exactly one retry")

    @mock.patch("time.sleep", return_value=None)
    def test_first_try_success_no_retry(self, _s):
        with mock.patch("requests.post", side_effect=[self._resp(200)]) as post:
            self.assertEqual(dr.get_macro_sentiment(), "BULLISH - test")
        self.assertEqual(post.call_count, 1)

    def test_missing_key_fallback(self):
        old = os.environ.pop("GEMINI_API_KEY", None)
        try:
            self.assertEqual(dr.get_macro_sentiment(),
                             "Sentiment data unavailable (API Key missing)")
        finally:
            if old is not None:
                os.environ["GEMINI_API_KEY"] = old


class TestMarketDataDegradation(unittest.TestCase):
    def test_yfinance_total_failure_yields_na(self):
        with mock.patch.object(dr.yf, "Ticker", side_effect=Exception("network down")):
            mkt, etf = dr.get_market_data()
        self.assertEqual(mkt, {"ES": "N/A", "NQ": "N/A", "YM": "N/A", "VIX": "N/A"})
        self.assertEqual(len(etf), 5)
        self.assertEqual(set(etf.values()), {"N/A"})


class TestReportAssembly(unittest.TestCase):
    def test_layout_unchanged(self):
        src_path = os.path.join(HERE, "..", "scripts", "daily_premarket_report.py")
        with open(src_path) as f:
            src = f.read()
        start = src.index('    report = f"\U0001F680 PRE-MARKET REPORT')
        end = src.index('    send_telegram(report)', start)
        block = textwrap.dedent(src[start:end])
        ns = {"today_str": "2026-08-28",
              "mkt_data": {"ES": "7751.25 (+0.12%)", "NQ": "29661.25 (-0.03%)",
                           "YM": "53727.00 (+0.07%)", "VIX": "14.46"},
              "etf_data": {"XLK": "Pre-Mkt: +2.92%", "XLF": "Pre-Mkt: -0.60%",
                           "XLE": "Pre-Mkt: -0.05%", "XLY": "Pre-Mkt: -0.99%",
                           "XLV": "Pre-Mkt: -0.79%"},
              "calendar_event": "No major macro events",
              "sentiment": "BEARISH - inflation concerns"}
        exec(compile(block, "<assembly>", "exec"), ns)
        report = ns["report"]
        self.assertIn("\U0001F680 PRE-MARKET REPORT \u2014 2026-08-28\n", report)
        self.assertIn("ES: 7751.25 (+0.12%) | NQ: 29661.25 (-0.03%)", report)
        self.assertIn("\U0001F4C9 VIX: 14.46\n", report)
        self.assertIn("\u2022 XLK: Pre-Mkt: +2.92%\n", report)
        self.assertTrue(report.endswith("\U0001F4F0 SENTIMENT: BEARISH - inflation concerns"))


import textwrap  # noqa: E402


class TestSampleDataPipeline(unittest.TestCase):
    """The repo's Quick Start promise: retrospective analysis runs on sample data."""

    def test_retrospective_on_sample_data(self):
        import subprocess
        sample = os.path.join(HERE, "..", "sample-data", "SignalTracker_sample.md")
        script = os.path.join(HERE, "..", "scripts", "retrospective_analysis.py")
        r = subprocess.run([sys.executable, script, "--file", sample],
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Total signals:", r.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
