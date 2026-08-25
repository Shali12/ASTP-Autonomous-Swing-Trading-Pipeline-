# Autonomous Swing Trading Pipeline

An autonomous AI-agent-driven pipeline that screens S&P 500 / Nasdaq 100 / S&P 400 stocks daily, logs confirmed swing-trading signals, tracks T+2/T+5/T+10 performance, and self-validates strategy improvements every 48 hours.

## Results (683 Completed Signals)

| Metric | T+2 | T+5 | T+10 |
|--------|-----|-----|------|
| Win Rate | 60.8% | 62.2% | 60.3% |
| Avg Win | +3.29% | +4.64% | +6.24% |
| Avg Loss | -3.04% | -3.98% | -6.00% |
| Profit Factor | 1.08 | 1.17 | 1.04 |

### By Setup (T+10)
| Setup | n | Win Rate | Avg Win | Avg Loss |
|-------|---|----------|---------|----------|
| BUY_A (Mean Reversion) | 94 | 69.1% | +7.72% | -6.62% |
| BUY_B (Breakout) | 589 | 58.9% | +5.96% | -5.93% |

### By RSI Range (T+10)
| RSI Range | n | Win Rate |
|-----------|---|----------|
| < 30 | 30 | 70.0% |
| 30-40 | 63 | 69.8% |
| 40-50 | 15 | 80.0% |
| 50-60 | 269 | 65.4% |
| 60-70 | 243 | 52.7% |
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
│   ├── retrospective_analysis.py      ← Pattern analysis by setup/RSI/volume
│   ├── review_validation.py           ← Self-validating improvement cycle
│   └── health_check.py                ← Automated pipeline quality checks
├── docs/
│   ├── pipeline-design.md             ← How the cron jobs fit together
│   ├── signal-tracker.md              ← How T+2/T+5/T+10 tracking works
│   └── self-validation.md             ← The 48hr improvement cycle
├── sample-data/
│   ├── SignalTracker_sample.md        ← 43 fake signals for testing
│   └── review_recommendations_sample.json  ← Sample recommendations
└── results/
    └── backtest-2026-08-23.md         ← Latest retrospective output
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
```

---

## The Two Trading Setups

### Setup A — Mean Reversion (BUY_A)
- **RSI:** < 35 (stock is oversold)
- **Volume:** Surge > 1.2x the 10-day average
- **Thesis:** Oversold stocks with volume confirmation tend to revert within 10 trading days
- **Win Rate:** 69.9% (n=93)

### Setup B — Breakout (BUY_B)
- **RSI:** < 65 (momentum exists but not overbought)
- **Volume:** Surge > 1.5x the 10-day average
- **Thesis:** Volume-confirmed breakouts with room before overbought tend to continue
- **Win Rate:** 58.7% (n=579)

---

## The Self-Validation Loop

Most trading systems backtest once and then blindly follow the strategy. This pipeline includes a **self-validation loop** that runs every 48 hours:

1. **Log recommendations** — When the retrospective analysis suggests a change (e.g., "tighten RSI threshold from 65 to 55"), the change is logged with a date and filter type
2. **Wait for data** — After 15+ new completed signals accumulate post-change, the validation script compares win rates before and after
3. **Decide** — If post-change win rate improved by >2%, the change is kept. If not, it's flagged for revert
4. **Report** — Results delivered to Telegram so the human can make the final call

This creates a feedback loop where the system continuously improves without blind trust in any single change.

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