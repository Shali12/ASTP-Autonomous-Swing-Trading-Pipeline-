# Signal Tracker

## How T+2/T+5/T+10 Tracking Works

When a signal is logged, the T+2, T+5, and T+10 columns are left empty. The `update` mode of `tracker.py` fills them in as time passes.

### Timeline

```
Day 0: Signal logged (T+2, T+5, T+10 all empty)
  |
Day 1: tracker.py update runs
  └─ days_elapsed = 1 → fills T+2 (price at trading day 2 after signal)
  |
Day 4: tracker.py update runs
  └─ days_elapsed = 4 → fills T+5 (price at trading day 5 after signal)
  |
Day 9: tracker.py update runs
  └─ days_elapsed = 9 → fills T+10 (price at trading day 10 after signal)
     └─ Also marks Outcome as WIN (+x.xx%) or LOSS (-x.xx%)
```

### Return Calculation

```
return = ((close_price_on_day_N - entry_price) / entry_price) * 100
```

- Entry price is the closing price on the signal date
- Close prices are fetched via yfinance
- If the return is outside ±50%, it's marked as `DATA_ERROR` (likely a stock split or data issue)

### Wilder's RSI

The screener uses Wilder's Smoothing for RSI calculation, not the default SMA method:

```python
delta = df['Close'].diff()
gain = delta.where(delta > 0, 0).ewm(alpha=1/14, adjust=False).mean()
loss = -delta.where(delta < 0, 0).ewm(alpha=1/14, adjust=False).mean()
rsi = 100 - (100 / (1 + (gain / loss)))
```

Key: `alpha=1/14, adjust=False` — this is Wilder's original smoothing method. Many libraries default to `adjust=True` which gives slightly different values.

### Data Validation

The tracker includes safeguards:
- **Duplicate prevention:** Won't log the same ticker within 10 trading days
- **Invalid price rejection:** Won't log NaN or zero entry prices
- **Sanity check:** Returns outside ±50% are marked as DATA_ERROR
- **Preamble resilience:** Parser handles changelog/notes prepended above the table header