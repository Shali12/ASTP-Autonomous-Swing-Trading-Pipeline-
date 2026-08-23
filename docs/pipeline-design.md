# Pipeline Design

## Overview

The pipeline runs on a schedule (cron) and consists of daily, weekly, and 48-hour cycles. Each step is a standalone Python script that reads/writes to a shared markdown file (`SignalTracker.md`).

## The SignalTracker.md File

This is the central data store. It's a markdown table — plain text, human-readable, Obsidian-compatible.

```
| Date | Ticker | Setup | Rank | Entry Price | RSI | Vol Ratio | Divergence | PEAD | Insider | 200SMA_Near | T+2 | T+5 | T+10 | Outcome |
|------|--------|-------|------|-------------|-----|-----------|------------|------|---------|-------------|-----|-----|------|---------|
| 2026-06-05 | UHS | BUY_A | 1 | $142.72 | 24.16 | 0.89x | No | N | N | N | +2.71% | +2.59% | -0.06% | LOSS (-0.06%) |
```

### Column Definitions

| Column | Description |
|--------|-------------|
| Date | Signal date (YYYY-MM-DD) |
| Ticker | Stock symbol |
| Setup | BUY_A (mean reversion) or BUY_B (breakout) |
| Rank | Rank within that day's screen (1 = best) |
| Entry Price | Closing price on signal date |
| RSI | Wilder's RSI (14-period, alpha=1/14, adjust=False) |
| Vol Ratio | Volume / 10-day average volume |
| Divergence | RSI divergence detected (Yes/No) |
| PEAD | Post-earnings announcement drift (Y/N) |
| Insider | Insider buying pattern (Single/Cluster/N) |
| 200SMA_Near | Price near 200-day SMA (Y/N) |
| T+2 | Return 2 trading days after signal |
| T+5 | Return 5 trading days after signal |
| T+10 | Return 10 trading days after signal |
| Outcome | WIN/LOSS with percentage |

## Daily Cycle (Mon-Fri)

### Step 1: Screening (06:30 MT)
- Scan ~1500 stocks (S&P 500, Nasdaq 100, S&P 400)
- Apply Setup A and Setup B criteria
- Output: List of BUY_A and BUY_B candidates with RSI, volume ratio, and other factors
- Confirmed signals are logged to SignalTracker.md

### Step 2: Health Check (06:40 MT)
- Verify screening script exited successfully
- Check that today's brief file was created
- Verify SignalTracker.md was updated with today's date
- Run LLM quality check (no duplicate signals, RSI in valid range, prices positive)
- Alert on Telegram if any check fails

### Step 3: Signal Update (16:30 MT)
- For each signal in SignalTracker.md:
  - If 2+ trading days have passed and T+2 is empty → fetch price, calculate return
  - If 5+ trading days have passed and T+5 is empty → fetch price, calculate return
  - If 10+ trading days have passed and T+10 is empty → fetch price, calculate return, mark WIN/LOSS
- Uses yfinance to fetch historical close prices

### Step 4: Health Check (16:40 MT)
- Verify update script exited successfully
- Check file is not stale (modified within 30 minutes)
- Count NaN values
- Alert silently (no Telegram message) if all OK

### Step 5: News Sentiment (17:00 MT)
- Scan headlines for active swing trade tickers
- Score sentiment from -1 (negative) to +1 (positive)
- Log to NewsTracker.md

## 48-Hour Review Cycle

Runs every 2 days at 06:00 MT. This is the **self-improvement** layer.

1. **Retrospective Analysis** — Run `retrospective_analysis.py`:
   - Overall win rates by T+2/T+5/T+10
   - Breakdown by setup (BUY_A vs BUY_B)
   - Breakdown by RSI range, volume ratio
   - Top/bottom performers

2. **Read-Only Backtest** — Run `threshold_backtest_template.py`:
   - Bucket signals by factor (RSI 45-55, 55-65, 65-75; Vol 1.5-2x, 2-3x, 3x+)
   - Apply minimum sample size of 15 per bucket
   - Report win rate for each bucket with n= and wins=

3. **Self-Validation** — Run `review_validation.py`:
   - Load prior cycle's recommendations from JSON
   - Split signals into pre-change and post-change groups
   - Compare win rates
   - If post > pre + 2% → keep change
   - If post <= pre + 2% → flag for revert
   - If <15 signals post-change → insufficient sample, keep monitoring

4. **Portfolio Audit** — Check active positions against current prices

5. **Deliver Summary** — Send results to Telegram

## Weekly Cycle (Sunday)

### Weekly Summary (08:00 MT)
- Run `tracker.py summary`
- Reports: total signals, completed count, win rate, avg win/loss, profit factor, best/worst

### Summary Health Check (08:10 MT)
- Verify summary script exited successfully
- Count total rows in tracker
- Alert if any errors