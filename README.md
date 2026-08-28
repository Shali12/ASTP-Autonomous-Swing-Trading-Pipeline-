# Autonomous Swing Trading Pipeline

An autonomous AI-agent-driven pipeline that screens S&P 500 / Nasdaq 100 / S&P 400 stocks daily, logs confirmed swing-trading signals, tracks T+2/T+5/T+10 performance, and self-validates strategy improvements every 48 hours.

## Results (694 Completed Signals)

| Metric | T+2 | T+5 | T+10 |
|--------|-----|-----|------|
| Win Rate | 61.0% | 62.2% | 60.4% |
| Avg Win | +3.34% | +4.64% | +6.24% |
| Avg Loss | -3.04% | -4.07% | -6.05% |
| Profit Factor | 1.10 | 1.14 | 1.03 |

### By Setup (T+10)
| Setup | n | Win Rate | Avg Win | Avg Loss |
|-------|---|----------|---------|----------|
| BUY_A (Mean Reversion) | 97 | 68.0% | +7.64% | -6.54% |
| BUY_B (Breakout) | 597 | 59.1% | +5.98% | -5.98% |

### By RSI Range (T+10)
| RSI Range | n | Win Rate |
|-----------|---|----------|
| < 30 | 30 | 70.0% |
| 30-40 | 67 | 67.2% |
| 40-50 | 15 | 80.0% |
| 50-60 | 280 | 65.7% |
| 60-70 | 250 | 53.2% |
| >= 70 | 52 | 46.2% |

### Key Finding
Lower RSI entries consistently outperform high-RSI entries. The RSI < 40 zone shows 70%+ win rates, while RSI >= 70 drops to 46%. This drove the strategy's RSI hard-skip tightening from 75 to 65 (July 2026) and is being evaluated for further tightening to 55.

---

## Architecture

```
                    DAILY PIPELINE (Mon-Fri)
                    ═══════════════════════
                    
  06:30  Daily Brief ───► Screener scans 1500 stocks
                           ├─ Setup A: RSI < 35, Vol Surge >1.2x (Mean Reversion)
                           └─ Setup B: RSI < 65, Vol Surge >1.5x (Breakout)
                           
  06:40  Health Check ──► Validates brief exit code, file freshness, 
                           signal count, tracker sync, LLM quality check
                           
  16:30  Tracker Update ► Fetches T+2/T+5/T+10 returns via yfinance
                           Marks WIN/LOSS outcomes
                           
  16:40  Health Check ──► Validates tracker update ran, no NaN values
                           
  17:00  News Sentiment ► Scans headlines for active swing trades
                           Scores sentiment (-1 to +1)
                           
                    
                    EVERY 48 HOURS
                    ══════════════
                    
  06:00  Review Cycle ──► 1. Retrospective analysis (patterns by setup/RSI/vol)
                           2. Read-only backtest (factor bucket validation, min n=15)
                           3. Self-validation: did prior changes IMPROVE win rate?
                              ├─ IMPROVED → keep change
                              ├─ NO IMPROVEMENT → revert change
                              └─ INSUFFICIENT SAMPLE → keep monitoring
                           4. Active portfolio audit
                           5. Trade performance audit
                           6. Deliver summary to Telegram
                    
                    
                    WEEKLY (Sunday)
                    ══════════════
                    
  08:00  Weekly Summary ► Win rate, profit factor, best/worst signals
  08:10  Health Check ──► Validates summary ran correctly
```

---

## Repository Structure

```
autonomous-swing-trading-pipeline/
├── README.md                          ← You are here
├── LICENSE                            ← MIT
├── requirements.txt                   ← Python dependencies
├── scripts/
│   ├── tracker.py                     ← Log signals, fetch returns, summarize
│   ├── daily_premarket_report.py      ← Pre-market futures/sectors/sentiment report
│   ├── retrospective_analysis.py      ← Pattern analysis by setup/RSI/volume
│   ├── review_validation.py           ← Self-validating improvement cycle
│   ├── health_check.py                ← Automated pipeline quality checks
│   └── validation_progress.py         ← Tracks self-validation readiness daily
├── tests/
│   └── test_health_fixes.py           ← 23 hermetic regression tests (no network)
│   └── test_validation_progress.py    ← Watcher tests (8)
├── docs/
│   ├── pipeline-design.md             ← How the cron jobs fit together
│   ├── signal-tracker.md              ← How T+2/T+5/T+10 tracking works
│   └── self-validation.md             ← The 48hr improvement cycle
├── sample-data/
│   ├── SignalTracker_sample.md        ← 43 fake signals for testing
│   └── review_recommendations_sample.json  ← Sample recommendations
└── results/
    ├── backtest-2026-08-28.md         ← Latest retrospective output
    └── validation-progress-2026-08-28.md ← Self-validation audit trail
```

---

## Quick Start

```bash
# 1. Install dependencies
pip install pandas numpy yfinance

# 2. Test with sample data
python3 scripts/retrospective_analysis.py --file sample-data/SignalTracker_sample.md

# 3. Test the summary
python3 scripts/tracker.py summary
# (set SIGNAL_TRACKER_FILE env var to point to your tracker file)

# 4. Test the self-validation
python3 scripts/review_validation.py \
  --signals sample-data/SignalTracker_sample.md \
  --recommendations sample-data/review_recommendations_sample.json

# 5. Run the test suite
python3 tests/test_health_fixes.py
python3 tests/test_validation_progress.py

# 6. See the self-validation progress demo (sample data)
SIGNAL_TRACKER_FILE=sample-data/SignalTracker_sample.md \
REVIEW_RECOMMENDATIONS_FILE=sample-data/review_recommendations_sample.json \
python3 scripts/validation_progress.py
```

---

## The Two Trading Setups

### Setup A — Mean Reversion (BUY_A)
- **RSI:** < 35 (stock is oversold)
- **Volume:** Surge > 1.2x the 10-day average
- **Thesis:** Oversold stocks with volume confirmation tend to revert within 10 trading days
- **Win Rate:** 68.0% (n=97)

### Setup B — Breakout (BUY_B)
- **RSI:** < 65 (momentum exists but not overbought)
- **Volume:** Surge > 1.5x the 10-day average
- **Thesis:** Volume-confirmed breakouts with room before overbought tend to continue
- **Win Rate:** 59.1% (n=597)

---

## The Self-Validation Loop

Most trading systems backtest once and then blindly follow the strategy. This pipeline includes a **self-validation loop** that runs every 48 hours:

1. **Log recommendations** — When the retrospective analysis suggests a change (e.g., "tighten RSI threshold from 65 to 55"), the change is logged with a date and filter type
2. **Wait for data** — After 15+ new completed signals accumulate post-change, the validation script compares win rates before and after
3. **Decide** — If post-change win rate improved by >2%, the change is kept. If not, it's flagged for revert
4. **Report** — Results delivered to Telegram so the human can make the final call

This creates a feedback loop where the system continuously improves without blind trust in any single change.

### Self-Validation Effectiveness (tracked live)

The loop isn't theoretical — every change is tracked from "implemented" to
"validated with data" by `scripts/validation_progress.py` (daily cron,
silent unless something changes). Changes currently in the pipeline:

| Change | Date | Post-change signals | Expected verdict |
|---|---|---|---|
| BUY_B RSI threshold 65 → 55 | 2026-08-25 | 16 logged, T+10 pending | week of Sep 7 |
| BUY_B Vol Ratio < 2.0x filter | 2026-08-25 | 16 logged, T+10 pending | week of Sep 7 |
| Crypto-proxy block (MSTR, COIN, MARA, …) | 2026-08-25 | 16 logged, T+10 pending | week of Sep 7 |

The first keep/revert verdicts land the week of **Sep 7, 2026**, once 15+
post-change signals complete their T+10 window. Full audit trail:
[results/validation-progress-2026-08-28.md](results/validation-progress-2026-08-28.md).

---

## How Production Deployment Works

In production, these scripts are orchestrated by an AI agent (Hermes Agent) running in Docker on a mini-PC. The agent:

1. Runs the daily screener via cron at 06:30 MT
2. Logs confirmed signals to `SignalTracker.md`
3. Fetches T+2/T+5/T+10 returns via yfinance at 16:30 MT
4. Runs health checks after each step
5. Performs the 48-hour review cycle
6. Delivers all results to Telegram

The scripts in this repo are the **standalone, portable versions** of the production scripts. They work without Hermes — you just need to run them yourself or set up your own cron.

---

## Tech Stack

- **Python 3.12+**
- **pandas / numpy** — Data analysis
- **yfinance** — Market data fetching
- **Markdown** — Signal tracker is a plain `.md` file (Obsidian-compatible)
- **Cron** — Scheduling (production uses Hermes Agent's built-in cron system)

---

## License

MIT — Use this however you want. Not financial advice. This is a hobby project for educational purposes.

---

## Disclaimer

This is NOT financial advice. This is a hobby project demonstrating autonomous AI agent pipelines for stock analysis. The author is not a registered investment advisor. All trading involves risk of loss. The signals tracked here were paper-traded or shadow-traded, not necessarily executed with real capital.