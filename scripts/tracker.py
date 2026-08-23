#!/usr/bin/env python3
"""
Signal Tracker — Logs swing trading signals and tracks T+2/T+5/T+10 performance.

Usage:
  python3 tracker.py log --ticker AAPL --setup BUY_A --rank 1 --entry 150.00 --rsi 28.50 --vol 1.25 --div true
  python3 tracker.py update
  python3 tracker.py summary
  python3 tracker.py delete-row --ticker AAPL --date 2026-01-15

Modes:
  log        — Add a new signal to the tracker
  update     — Fetch T+2/T+5/T+10 returns via yfinance for signals due for update
  summary    — Print weekly performance summary (win rate, avg win/loss, profit factor)
  delete-row — Remove a specific signal by ticker + date

Requirements:
  pip install pandas numpy yfinance
"""

import pandas as pd
import numpy as np
import yfinance as yf
import datetime
import os
import sys

# Configurable path — defaults to current directory
TRACKER_FILE = os.environ.get("SIGNAL_TRACKER_FILE", "SignalTracker.md")


def _find_table(lines):
    """Find the header row index in a markdown table that may have a preamble."""
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith("|") and ("Date" in s or "Ticker" in s or "Signal Date" in s):
            return i
    return None


def initialize_tracker():
    """Create the tracker file if it doesn't exist."""
    if not os.path.exists(TRACKER_FILE):
        os.makedirs(os.path.dirname(TRACKER_FILE) if os.path.dirname(TRACKER_FILE) else ".", exist_ok=True)
        header = "| Date | Ticker | Setup | Rank | Entry Price | RSI | Vol Ratio | Divergence | PEAD | Insider | 200SMA_Near | T+2 | T+5 | T+10 | Outcome |\n"
        header += "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |\n"
        with open(TRACKER_FILE, "w") as f:
            f.write(header + "\n")


def log_signal(ticker, setup, rank, entry, rsi, vol_ratio, divergence, pead="N", insider="N", sma_near="N"):
    """Log a new swing trading signal."""
    initialize_tracker()

    if entry is None or pd.isna(entry) or entry <= 0:
        print(f"Warning: Invalid entry price ({entry}) for {ticker}. Skipping.")
        return

    # Check for duplicate within 10 trading days
    with open(TRACKER_FILE, "r") as f:
        lines = f.readlines()

    hidx = _find_table(lines)
    if hidx is not None and len(lines) > hidx + 2:
        for row in reversed(lines[hidx + 2:]):
            cols = [c.strip() for c in row.split('|')[1:-1]]
            if len(cols) < 2:
                continue
            if cols[1] == ticker:
                try:
                    sig_date = np.datetime64(cols[0])
                    days_elapsed = np.busday_count(sig_date, np.datetime64('today'))
                    if days_elapsed < 10:
                        print(f"Skipping {ticker} — duplicate within 10 trading days.")
                        return
                except:
                    pass
                break

    date_str = datetime.datetime.now().strftime("%Y-%m-%d")
    div_str = "Yes" if divergence else "No"

    row = f"| {date_str} | {ticker} | {setup} | {rank} | ${entry:.2f} | {rsi:.2f} | {vol_ratio:.2f}x | {div_str} | {pead} | {insider} | {sma_near} | | | | |\n"

    with open(TRACKER_FILE, "a") as f:
        f.write(row)
    print(f"Logged signal for {ticker}")


def delete_row(ticker, date_str):
    """Remove a specific signal row by ticker and date."""
    if not os.path.exists(TRACKER_FILE):
        print("SignalTracker.md not found.")
        return

    with open(TRACKER_FILE, "r") as f:
        lines = f.readlines()

    hidx = _find_table(lines) or 0
    updated = lines[:hidx + 2]
    deleted = False

    for line in lines[hidx + 2:]:
        stripped = line.strip()
        if not stripped:
            continue
        cols = [c.strip() for c in stripped.split('|')[1:-1]]
        if len(cols) < 2:
            continue
        if cols[0] == date_str and cols[1] == ticker:
            deleted = True
            continue
        updated.append(line)

    if deleted:
        with open(TRACKER_FILE, "w") as f:
            f.writelines(updated)
        print(f"Deleted row for {ticker} on {date_str}")
    else:
        print(f"No matching row for {ticker} on {date_str}")


def update_signals():
    """Fetch T+2/T+5/T+10 returns for signals that are due."""
    initialize_tracker()
    with open(TRACKER_FILE, "r") as f:
        lines = f.readlines()

    hidx = _find_table(lines)
    if hidx is None:
        return

    preamble = lines[:hidx]
    header = lines[hidx]
    separator = lines[hidx + 1] if hidx + 1 < len(lines) else ""
    body = lines[hidx + 2:]

    updated_rows = []
    changed = False
    today = np.datetime64('today')

    for row in body:
        raw = row.rstrip("\n")
        stripped = raw.strip()
        if not stripped:
            updated_rows.append(raw)
            continue

        cols = [c.strip() for c in stripped.split('|')[1:-1]]
        if cols and all(c in ('', '-', ':') for c in cols):
            updated_rows.append(raw)
            continue
        if cols and cols[0].lower() in ('date', 'signal date'):
            updated_rows.append(raw)
            continue
        if len(cols) < 11:
            updated_rows.append(raw)
            continue

        try:
            sig_date = np.datetime64(cols[0])
            ticker = cols[1]
            entry_price = float(cols[4].replace('$', ''))
        except (ValueError, IndexError):
            updated_rows.append("| " + " | ".join(cols) + " |")
            continue

        days_elapsed = np.busday_count(sig_date, today)

        # T+2 (index 11)
        if days_elapsed >= 1 and not cols[11]:
            try:
                df = yf.download(ticker, start=str(sig_date), progress=False)
                if len(df) >= 3:
                    price = df['Close'].iloc[2]
                    if isinstance(price, pd.Series):
                        price = price.iloc[0]
                    ret = ((price - entry_price) / entry_price) * 100
                    cols[11] = f"{ret:+.2f}%" if -50 <= ret <= 50 else "DATA_ERROR"
                    changed = True
            except Exception as e:
                print(f"Error T+2 for {ticker}: {e}")

        # T+5 (index 12)
        if days_elapsed >= 4 and not cols[12]:
            try:
                df = yf.download(ticker, start=str(sig_date), progress=False)
                if len(df) >= 6:
                    price = df['Close'].iloc[5]
                    if isinstance(price, pd.Series):
                        price = price.iloc[0]
                    ret = ((price - entry_price) / entry_price) * 100
                    cols[12] = f"{ret:+.2f}%" if -50 <= ret <= 50 else "DATA_ERROR"
                    changed = True
            except Exception as e:
                print(f"Error T+5 for {ticker}: {e}")

        # T+10 (index 13)
        if days_elapsed >= 9 and not cols[13]:
            try:
                df = yf.download(ticker, start=str(sig_date), progress=False)
                if len(df) >= 11:
                    price = df['Close'].iloc[10]
                    if isinstance(price, pd.Series):
                        price = price.iloc[0]
                    ret = ((price - entry_price) / entry_price) * 100
                    if -50 <= ret <= 50:
                        cols[13] = f"{ret:+.2f}%"
                        cols[14] = f"{'WIN' if ret > 0 else 'LOSS'} ({ret:+.2f}%)"
                    else:
                        cols[13] = "DATA_ERROR"
                        cols[14] = ""
                    changed = True
            except Exception as e:
                print(f"Error T+10 for {ticker}: {e}")

        updated_rows.append("| " + " | ".join(cols) + " |")

    if changed:
        with open(TRACKER_FILE, "w") as f:
            f.write("".join(preamble) + header.rstrip("\n") + "\n" + separator.rstrip("\n") + "\n" + "\n".join(updated_rows) + "\n")
        print("Updated signal performance metrics.")
    else:
        print("No signals ready for update.")


def summary_signals():
    """Print a performance summary of completed signals."""
    if not os.path.exists(TRACKER_FILE):
        print("No SignalTracker.md found.")
        return

    with open(TRACKER_FILE, "r") as f:
        lines = f.readlines()

    hidx = _find_table(lines)
    if hidx is None:
        print("No table found.")
        return

    total = 0
    completed = []

    for row in lines[hidx + 2:]:
        row = row.strip()
        if not row:
            continue
        cols = [c.strip() for c in row.split('|')[1:-1]]
        if len(cols) < 15 or (cols and cols[0].lower() == 'date'):
            continue
        total += 1
        t10 = cols[13]
        if t10 and '%' in t10:
            try:
                completed.append((cols[1], float(t10.replace('%', ''))))
            except ValueError:
                continue

    n = len(completed)
    if n == 0:
        print(f"No completed signals yet. {total} signals being tracked.")
        return

    wins = [r for _, r in completed if r > 0]
    losses = [r for _, r in completed if r <= 0]
    wr = len(wins) / n * 100
    avg_w = np.mean(wins) if wins else 0
    avg_l = np.mean(losses) if losses else 0
    pf = abs(avg_w) / abs(avg_l) if avg_l != 0 else float('inf')
    best = max(completed, key=lambda x: x[1])
    worst = min(completed, key=lambda x: x[1])

    print(f"""
SIGNAL SUMMARY
{'-'*40}
Total Signals:  {total}
Completed (T+10): {n}
Win Rate:       {wr:.1f}%
Avg Win:        {avg_w:+.2f}%
Avg Loss:       {avg_l:+.2f}%
Profit Factor:  {pf:.2f}
Best:           {best[0]} ({best[1]:+.2f}%)
Worst:          {worst[0]} ({worst[1]:+.2f}%)
{'-'*40}
""")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Swing trading signal tracker")
    parser.add_argument("mode", choices=["log", "update", "summary", "delete-row"])
    parser.add_argument("--ticker")
    parser.add_argument("--setup")
    parser.add_argument("--rank", type=int)
    parser.add_argument("--entry", type=float)
    parser.add_argument("--rsi", type=float)
    parser.add_argument("--vol", type=float)
    parser.add_argument("--div", type=str)
    parser.add_argument("--pead", type=str, default="N")
    parser.add_argument("--insider", type=str, default="N")
    parser.add_argument("--sma_near", type=str, default="N")
    parser.add_argument("--date", type=str)
    args = parser.parse_args()

    if args.mode == "log":
        div_bool = args.div.lower() == "true" if args.div else False
        log_signal(args.ticker, args.setup, args.rank, args.entry, args.rsi, args.vol, div_bool, args.pead, args.insider, args.sma_near)
    elif args.mode == "update":
        update_signals()
    elif args.mode == "summary":
        summary_signals()
    elif args.mode == "delete-row":
        if not args.ticker or not args.date:
            print("Error: --ticker and --date required for delete-row")
            sys.exit(1)
        delete_row(args.ticker, args.date)