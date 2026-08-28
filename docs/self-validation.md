# Self-Validation: The 48-Hour Improvement Cycle

## Problem

Most trading backtesting systems work like this:
1. Backtest a strategy
2. Deploy it
3. Never check if it's still working

This leads to strategy decay — market conditions change, and a strategy that worked last year may not work this year.

## Solution

This pipeline includes a **self-validation loop** that runs every 48 hours:

```
    ┌──────────────────────────────────────────────────┐
    │                                                  │
    │  1. RETROSPECTIVE                                │
    │     Analyze 672+ signals for patterns            │
    │     "RSI < 40 wins 70%, RSI > 70 wins 46%"      │
    │                                                  │
    │  2. RECOMMEND CHANGE                             │
    │     "Tighten BUY_B RSI threshold from 65 to 55"  │
    │     Log to review_recommendations.json            │
    │                                                  │
    │  3. WAIT (15+ new signals accumulate)            │
    │                                                  │
    │  4. VALIDATE (next cycle, 48hrs later)           │
    │     Compare win rate BEFORE vs AFTER change date  │
    │     ├─ IMPROVED (+2% or more) → KEEP             │
    │     ├─ NO IMPROVEMENT → REVERT                   │
    │     └─ INSUFFICIENT SAMPLE → KEEP MONITORING     │
    │                                                  │
    │  5. REPORT                                       │
    │     Deliver results to Telegram                   │
    │                                                  │
    └──────────────────────────────────────────────────┘
```

## The Recommendations Log

Changes are tracked in a JSON file:

```json
{
  "last_cycle": "2026-08-23",
  "changes": [
    {
      "date": "2026-08-23",
      "description": "Tighten BUY_B RSI threshold from 65 to 55",
      "filter": "rsi_lt_55",
      "expected_impact": "Improve BUY_B win rate from 58.7% toward 65%+"
    }
  ]
}
```

## Validation Logic

The `review_validation.py` script:

1. Loads the recommendations JSON
2. Parses all completed WIN/LOSS signals from SignalTracker.md
3. For each recommendation:
   - Splits signals into `pre` (before change date) and `post` (after change date)
   - If a filter is specified (e.g., `rsi_lt_55`), applies it to both groups
   - Calculates win rate for each group
   - If `post_wr > pre_wr + 2.0` → status: `improved`, action: `keep`
   - If `post_wr <= pre_wr + 2.0` → status: `no_improvement`, action: `revert`
   - If either group has `< 15` signals → status: `insufficient_sample`, action: `N/A`

## Tracking Progress Daily

Waiting for 15+ completed signals used to be a black box. The watcher
script makes it observable:

```bash
python3 scripts/validation_progress.py
```

For every pending change it counts post-change signals (logged vs
completed through T+10), shows the T+10 completion window for the current
cohort, and prints ONLY when something changed:

- **baseline** — first run establishes the tracked state
- **progress** — new post-change signals logged or completed
- **STAGNATION ALERT** — no new post-change signal for 3+ trading days
- **VALIDATION READY** — a change reached 15+ completed signals; the next
  48h cycle will issue a real keep/revert verdict

Missing input files exit non-zero (so a cron job alerts instead of
silently tracking nothing). In production this runs as a daily cron; the
real milestone history is kept in `results/validation-progress-*.md`.

## Why This Matters

This is the difference between:
- **Blind optimization:** "I changed a threshold and hope it works"
- **Validated optimization:** "I changed a threshold, waited for 15+ signals, compared win rates, and confirmed a 4% improvement before keeping the change"

The self-validation loop prevents the most common failure mode in algorithmic trading: overfitting to recent data without checking if changes actually generalize.