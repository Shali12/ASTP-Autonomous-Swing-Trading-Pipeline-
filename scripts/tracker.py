#!/usr/bin/env python3
"""
Signal Tracker — Logs swing trading signals and tracks T+2/T+5/T+10 performance.

Usage:
  python3 tracker.py log --ticker AAPL --setup BUY_A --rank 1 --entry 150.00 --rsi 28.50 --vol 1.25 --div true
  python3 tracker.py update
  python3 tracker.py summary
  python3 tracker.py delete-row --ticker AAPL --date 2026-01-15

Configuration (optional):
  SIGNAL_TRACKER_FILE  path to SignalTracker.md (default: SignalTracker.md)

The tracker table has 16 columns (Signal Date .. Catalyst). log_signal
dedupes: the same ticker is skipped within 10 trading days, so re-running
the daily brief never duplicates rows.

Requirements:
  pip install pandas numpy yfinance
"""

import pandas as pd
import numpy as np
import yfinance as yf
import datetime
import os
import sys

TRACKER_FILE = os.environ.get("SIGNAL_TRACKER_FILE", "SignalTracker.md")


def _find_table(lines):
    """Return the index of the markdown table header row (the one starting
    with '|' and containing a Date/Ticker column). Returns None if not found.
    This makes the parser resilient to changelog/notes lines prepended above
    the table."""
    for i, line in enumerate(lines):
            s = line.strip()
            if s.startswith("|") and ("Date" in s or "Ticker" in s or "Signal Date" in s):
                return i
    return None


def initialize_tracker():
    if not os.path.exists(TRACKER_FILE):
        os.makedirs(os.path.dirname(TRACKER_FILE), exist_ok=True)
        header = "| Signal Date | Ticker | Setup | Rank | Entry Price | RSI | Vol Ratio | Divergence | PEAD | Insider | 200SMA_Near | T+2 | T+5 | T+10 | Outcome | Catalyst |\n"
        header += "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |\n"
        with open(TRACKER_FILE, "w") as f:
            f.write(header + "\n")
    else:
        # If file exists, ensure header includes Catalyst column
        with open(TRACKER_FILE, "r") as f:
            lines = f.readlines()
        hidx = _find_table(lines)
        if hidx is not None:
            header_line = lines[hidx].strip()
            if "Catalyst" not in header_line:
                # Insert Catalyst column before the final closing pipe
                # Assuming header ends with "| Outcome |"
                # We'll replace "| Outcome |" with "| Outcome | Catalyst |"
                new_header = header_line.rstrip("|") + " Catalyst |\n"
                lines[hidx] = new_header
                # Also need to add a separator line for the new column
                sep_idx = hidx + 1
                if sep_idx < len(lines):
                    sep_line = lines[sep_idx].strip()
                    # Add an extra --- for the new column
                    new_sep = sep_line + " --- |\n"
                    lines[sep_idx] = new_sep
                # For each data row, add an empty field at the end
                for i in range(hidx + 2, len(lines)):
                    line = lines[i].rstrip("\n")
                    if line.strip() == "":
                        continue
                    # Ensure line starts and ends with pipe
                    if line.startswith("|") and line.endswith("|"):
                        parts = line.split("|")
                        if len(parts) >= 2:
                            parts = parts[:-1] + [""] + parts[-1:]
                            lines[i] = "|".join(parts) + "\n"
                        else:
                            lines[i] = line + " |\n"
                    else:
                        lines[i] = line + " |\n"
                with open(TRACKER_FILE, "w") as f:
                    f.writelines(lines)
                print("Updated SignalTracker header to include Catalyst column.")


def log_signal(ticker, setup, rank, entry, rsi, vol_ratio, divergence, pead="N", insider="N", sma_near="N", catalyst=""):
    initialize_tracker()

    # Validation: Prevent logging NaN or zero prices
    if entry is None or pd.isna(entry) or entry <= 0:
        print(f"⚠️ Warning: Invalid entry price ({entry}) for {ticker}. Skipping log.")
        return

    # Check for existing signals within 10 trading days
    if os.path.exists(TRACKER_FILE):
        with open(TRACKER_FILE, "r") as f:
            lines = f.readlines()

    hidx = _find_table(lines)
    if len(lines) > 2 and hidx is not None:
        rows = lines[hidx + 2:]
        for row in reversed(rows):  # Check newest first
            cols = [c.strip() for c in row.split('|')[1:-1]]
            if len(cols) < 2:
                continue

            row_ticker = cols[1]
            if row_ticker == ticker:
                sig_date = np.datetime64(cols[0])
                today = np.datetime64('today')
                days_elapsed = np.busday_count(sig_date, today)
                if days_elapsed < 10:
                    return  # Skip silently
                break  # Found most recent, no need to check further back

    date_str = datetime.datetime.now().strftime("%Y-%m-%d")
    div_str = "Yes" if divergence else "No"

    row = f"| {date_str} | {ticker} | {setup} | {rank} | ${entry:.2f} | {rsi:.2f} | {vol_ratio:.2f}x | {div_str} | {pead} | {insider} | {sma_near} | | | | | {catalyst} |\n"

    with open(TRACKER_FILE, "a") as f:
        f.write(row)
    print(f"Logged signal for {ticker}")


def delete_row(ticker, date_str):
    """Removes a specific signal row based on ticker and date."""
    if not os.path.exists(TRACKER_FILE):
        print("SignalTracker.md not found.")
        return

    with open(TRACKER_FILE, "r") as f:
        lines = f.readlines()

    updated_lines = []
    row_deleted = False

    # Keep preamble (changelog) + header + separator, filter the rest
    hidx = _find_table(lines) or 0
    updated_lines.extend(lines[:hidx + 2])

    for line in lines[hidx + 2:]:
        line = line.strip()
        if not line:
            continue

        cols = [c.strip() for c in line.split('|')[1:-1]]
        if len(cols) < 2:
            continue

        # Date is col 0, Ticker is col 1
        if cols[0] == date_str and cols[1] == ticker:
            row_deleted = True
            continue  # Skip this row

        updated_lines.append(line + "\n")

    if row_deleted:
        with open(TRACKER_FILE, "w") as f:
            f.write("".join(updated_lines))
        print(f"Successfully deleted row for {ticker} on {date_str}")
    else:
        print(f"No matching row found for {ticker} on {date_str}")


def update_signals():
    initialize_tracker()
    with open(TRACKER_FILE, "r") as f:
        lines = f.readlines()

    if len(lines) <= 2:  # Header only
        return

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
        # Skip the markdown separator row
        if cols and all(c in ('', '-', ':') for c in cols):
            updated_rows.append(raw)
            continue
        # Skip the header row itself
        if cols and cols[0].lower() in ('date', 'signal date'):
            updated_rows.append(raw)
            continue
        if len(cols) < 11:
            updated_rows.append(raw)
            continue

        # Cols: 0:Date, 1:Ticker, 2:Setup, 3:Rank, 4:Entry Price, 5:RSI, 6:Vol Ratio, 7:Divergence, 8:PEAD, 9:Insider, 10:200SMA_Near, 11:T+2, 12:T+5, 13:T+10, 14:Outcome, 15:Catalyst
        # Note: we added Catalyst at index 15

        sig_date = np.datetime64(cols[0])
        ticker = cols[1]
        try:
            entry_price = float(cols[4].replace('$', ''))
        except (ValueError, IndexError):
            updated_rows.append("| " + " | ".join(cols) + " |")
            continue

        # Calculate trading days elapsed
        days_elapsed = np.busday_count(sig_date, today)

        # Update T+2 (index 11)
        if days_elapsed >= 1 and not cols[11]:
            try:
                df = yf.download(ticker, start=str(sig_date), progress=False)
                if len(df) >= 3:
                    price_t2 = df['Close'].iloc[2]
                    if isinstance(price_t2, pd.Series):
                        price_t2 = price_t2.iloc[0]
                    ret = ((price_t2 - entry_price) / entry_price) * 100
                    if -50 <= ret <= 50:
                        cols[11] = f"{ret:+.2f}%"
                    else:
                        cols[11] = "DATA_ERROR"
                    changed = True
            except Exception as e:
                print(f"Error updating T+2 for {ticker}: {e}")

        # Update T+5 (index 12)
        if days_elapsed >= 4 and not cols[12]:
            try:
                df = yf.download(ticker, start=str(sig_date), progress=False)
                if len(df) >= 6:
                    price_t5 = df['Close'].iloc[5]
                    if isinstance(price_t5, pd.Series):
                        price_t5 = price_t5.iloc[0]
                    ret = ((price_t5 - entry_price) / entry_price) * 100
                    if -50 <= ret <= 50:
                        cols[12] = f"{ret:+.2f}%"
                    else:
                        cols[12] = "DATA_ERROR"
                    changed = True
            except Exception as e:
                print(f"Error updating T+5 for {ticker}: {e}")

        # Update T+10 (index 13)
        if days_elapsed >= 9 and not cols[13]:
            try:
                df = yf.download(ticker, start=str(sig_date), progress=False)
                if len(df) >= 11:
                    price_t10 = df['Close'].iloc[10]
                    if isinstance(price_t10, pd.Series):
                        price_t10 = price_t10.iloc[0]
                    ret = ((price_t10 - entry_price) / entry_price) * 100
                    if -50 <= ret <= 50:
                        cols[13] = f"{ret:+.2f}%"
                        # Mark Outcome (index 14)
                        outcome_str = "WIN" if ret > 0 else "LOSS"
                        cols[14] = f"{outcome_str} ({ret:+.2f}%)"
                    else:
                        cols[13] = "DATA_ERROR"
                        cols[14] = ""
                    changed = True
            except Exception as e:
                print(f"Error updating T+10 for {ticker}: {e}")

        updated_rows.append("| " + " | ".join(cols) + " |")

    if changed:
        preamble_text = "".join(preamble)
        header_text = header.rstrip("\n")
        sep_text = separator.rstrip("\n")
        with open(TRACKER_FILE, "w") as f:
            f.write(preamble_text + header_text + "\n" + sep_text + "\n" + "\n".join(updated_rows) + "\n")
        print("Updated signal performance metrics.")
    else:
        print("No signals ready for update.")


def summary_signals():
    if not os.path.exists(TRACKER_FILE):
        print("No SignalTracker.md found.")
        return

    with open(TRACKER_FILE, "r") as f:
        lines = f.readlines()

    if len(lines) <= 2:
        print("No signals logged yet.")
        return

    rows = lines[(_find_table(lines) or 0) + 2:]
    total_signals = 0
    completed_signals = []  # List of (ticker, return_pct)

    for row in rows:
        row = row.strip()
        if not row:
            continue
        cols = [c.strip() for c in row.split('|')[1:-1]]
        if len(cols) < 15:
            continue
        if cols and cols[0].lower() == 'date':
            continue

        total_signals += 1
        t10_val = cols[13]
        if t10_val and '%' in t10_val:
            try:
                ret_pct = float(t10_val.replace('%', ''))
                completed_signals.append((cols[1], ret_pct))
            except ValueError:
                continue

    completed_count = len(completed_signals)
    if completed_count == 0:
        print(f"No completed signals yet. {total_signals} signals being tracked.")
        return

    wins = [ret for ticker, ret in completed_signals if ret > 0]
    losses = [ret for ticker, ret in completed_signals if ret <= 0]

    win_rate = (len(wins) / completed_count) * 100
    avg_win = np.mean(wins) if wins else 0
    avg_loss = np.mean(losses) if losses else 0
    profit_factor = abs(avg_win) / abs(avg_loss) if avg_loss != 0 else float('inf')

    best_signal = max(completed_signals, key=lambda x: x[1])
    worst_signal = min(completed_signals, key=lambda x: x[1])

    summary = [
        "📊 WEEKLY SIGNAL SUMMARY",
        "-------------------------",
        f"Total Signals Logged: {total_signals}",
        f"Completed (T+10):    {completed_count}",
        f"Win Rate:            {win_rate:.2f}%",
        f"Avg Win:             {avg_win:+.2f}%",
        f"Avg Loss:            {avg_loss:+.2f}%",
        f"Profit Factor:       {profit_factor:.2f}",
        f"Best Signal:         {best_signal[0]} ({best_signal[1]:+.2f}%)",
        f"Worst Signal:        {worst_signal[0]} ({worst_signal[1]:+.2f}%)",
        "-------------------------"
    ]

    print("\n".join(summary))


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
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
    parser.add_argument("--catalyst", type=str, default="")
    parser.add_argument("--date", type=str)

    args = parser.parse_args()

    if args.mode == "log":
        div_bool = args.div.lower() == "true" if args.div else False
        log_signal(args.ticker, args.setup, args.rank, args.entry, args.rsi, args.vol, div_bool, args.pead, args.insider, args.sma_near, args.catalyst)
    elif args.mode == "update":
        update_signals()
    elif args.mode == "summary":
        summary_signals()
    elif args.mode == "delete-row":
        if not args.ticker or not args.date:
            print("Error: --ticker and --date are required for delete-row mode.")
            sys.exit(1)
        delete_row(args.ticker, args.date)