# Self-Validation Progress Log

This log is the audit trail for the [self-validation loop](../docs/self-validation.md):
it tracks each strategy change from "implemented" to "validated with data".

**How to read this:** after a change is implemented, the pipeline needs
15+ *completed* signals (T+10 outcome filled) logged **after** the change
date before the 48h review cycle can issue a keep/revert verdict. The
watcher script (`scripts/validation_progress.py`) counts this daily; each
milestone gets appended below.

---

## 2026-08-28 — Baseline (watcher established)

Changes pending validation:

| Change | Date | Post-change signals logged | Completed (T+10) | Status |
|---|---|---|---|---|
| SignalTracker parser fix (changelog preamble, Catalyst column) | 2026-08-23 | 26 | 0 | pending |
| Screener-retrospective script operational | 2026-08-23 | 26 | 0 | pending |
| BUY_B RSI threshold 65 → 55 | 2026-08-25 | 16 | 0 | pending |
| BUY_B Vol Ratio < 2.0x filter | 2026-08-25 | 16 | 0 | pending |
| Crypto-proxy block (MSTR, MARA, RIOT, COIN, HOOD, …) | 2026-08-25 | 16 | 0 | pending |

Notes:

1. The three 2026-08-25 changes share the same post-change cohort (16
   signals logged Aug 25-28); the two 2026-08-23 changes additionally see
   the 10 signals logged Aug 23-24.
2. Post-change counts are the *feed* — no T+10 outcome exists yet for any
   of them, so `review_validation.py` correctly reports
   `insufficient_sample` (pre_n: 694, post_n: 0).
3. T+10 completion window for the current cohort: **2026-09-07 to 2026-09-11**.
4. Watcher: daily cron, silent unless progress/stagnation/ready-state changes.
   A stagnation alert fires if no new post-change signal logs for 3+ trading days.

**Next update:** when completions start landing (week of Sep 7) or a
milestone fires.
