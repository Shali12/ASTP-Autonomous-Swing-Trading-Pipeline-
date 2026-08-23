# How To Use This Repo

## For Developers / Traders

### Option 1: Test with Sample Data

```bash
# Clone the repo
git clone https://github.com/Shali12/autonomous-swing-trading-pipeline.git
cd autonomous-swing-trading-pipeline

# Install dependencies
pip install -r requirements.txt

# Run retrospective analysis on sample data
python3 scripts/retrospective_analysis.py --file sample-data/SignalTracker_sample.md

# Run signal summary
SIGNAL_TRACKER_FILE=sample-data/SignalTracker_sample.md python3 scripts/tracker.py summary

# Run self-validation
python3 scripts/review_validation.py \
  --signals sample-data/SignalTracker_sample.md \
  --recommendations sample-data/review_recommendations_sample.json

# Run health check (will show FAILED — that's expected without cron)
SIGNAL_TRACKER_FILE=sample-data/SignalTracker_sample.md python3 scripts/health_check.py tracker
```

### Option 2: Use Your Own Data

1. Create your own `SignalTracker.md` file with the same table format
2. Log signals using `tracker.py log`:

```bash
python3 scripts/tracker.py log \
  --ticker AAPL \
  --setup BUY_A \
  --rank 1 \
  --entry 150.00 \
  --rsi 28.50 \
  --vol 1.25 \
  --div true
```

3. Update returns daily:

```bash
SIGNAL_TRACKER_FILE=my_signals.md python3 scripts/tracker.py update
```

4. Get summary:

```bash
SIGNAL_TRACKER_FILE=my_signals.md python3 scripts/tracker.py summary
```

5. Run retrospective:

```bash
python3 scripts/retrospective_analysis.py --file my_signals.md
```

### Option 3: Full Cron Setup

Create your own cron jobs to automate the pipeline:

```cron
# Daily screening at 06:30
30 6 * * 1-5 cd /path/to/repo && python3 scripts/tracker.py update >> logs/tracker.log 2>&1

# 48-hour review cycle
0 6 */2 * * cd /path/to/repo && python3 scripts/retrospective_analysis.py >> logs/retro.log 2>&1

# Weekly summary on Sundays
0 8 * * 0 cd /path/to/repo && python3 scripts/tracker.py summary >> logs/summary.log 2>&1
```

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `SIGNAL_TRACKER_FILE` | `SignalTracker.md` | Path to your tracker file |
| `BRIEF_DIR` | `.` | Directory where daily briefs are stored |
| `LOG_DIR` | `logs` | Directory for exit code and log files |

## File Format

The SignalTracker.md file is a standard markdown table. You can edit it in any text editor, Obsidian, or even Excel (with a markdown export).

The parser handles:
- Changelog/notes prepended above the table (blockquote lines starting with `>`)
- Missing columns (fills with empty strings)
- DATA_ERROR values (treated as non-completed signals)

## Questions?

Open an issue on GitHub. This is a hobby project — I respond when I can.