#!/usr/bin/env python3
"""
Retrospective Analysis — Analyzes SignalTracker.md for performance patterns.

Usage:
  python3 retrospective_analysis.py                          # Uses default SignalTracker.md
  python3 retrospective_analysis.py --file path/to/data.md   # Custom file path

Requirements:
  pip install pandas numpy

Output:
  Prints analysis to stdout — overall win rates, breakdowns by setup,
  RSI range, volume ratio, and top/bottom performers.
"""

import pandas as pd
import numpy as np
import os
import sys
import argparse

def _find_table(lines):
    """Find the header row index in a markdown table."""
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith("|") and ("Date" in s or "Ticker" in s or "Signal Date" in s):
            return i
    return None


def load_tracker(filepath):
    """Load SignalTracker.md into a DataFrame."""
    if not os.path.exists(filepath):
        print(f"File not found: {filepath}")
        return None

    with open(filepath, "r") as f:
        lines = f.readlines()

    hidx = _find_table(lines)
    if hidx is None:
        print("Could not find table header")
        return None

    # Use standard header names — the file may have shortened column names
    headers = ["Date", "Ticker", "Setup", "Rank", "Entry Price", "RSI",
               "Vol Ratio", "Divergence", "PEAD", "Insider", "200SMA_Near",
               "T+2", "T+5", "T+10", "Outcome", "Catalyst"]

    data = []
    for line in lines[hidx + 2:]:
        line = line.strip()
        if not line or line.startswith(">") or not line.startswith("|"):
            continue
        cols = [c.strip() for c in line.split('|') if c.strip()]
        if len(cols) >= 16:
            data.append(cols[:16])
        elif len(cols) == 15:
            data.append(cols + [""])

    if not data:
        return pd.DataFrame(columns=headers)

    return pd.DataFrame(data, columns=headers)


def parse_pct(val):
    """Parse percentage string like '+5.23%' to float."""
    if pd.isna(val) or val == '' or val == 'DATA_ERROR':
        return np.nan
    try:
        return float(str(val).replace('%', ''))
    except (ValueError, AttributeError):
        return np.nan


def analyze_patterns(df):
    """Analyze performance patterns and print results."""
    print("=" * 60)
    print("SCREENER RETROSPECTIVE ANALYSIS")
    print("=" * 60)

    pct_cols = ['T+2', 'T+5', 'T+10']
    for col in pct_cols:
        if col in df.columns:
            df[f'{col}_pct'] = df[col].apply(parse_pct)

    print(f"\nTotal signals: {len(df)}")

    for horizon in ['T+2', 'T+5', 'T+10']:
        col = f'{horizon}_pct'
        if col not in df.columns:
            continue
        valid = df[col].dropna()
        if len(valid) == 0:
            print(f"\n{horizon}: No data")
            continue
        wins = valid[valid > 0]
        losses = valid[valid <= 0]
        wr = len(wins) / len(valid) * 100
        avg_w = wins.mean() if len(wins) > 0 else 0
        avg_l = losses.mean() if len(losses) > 0 else 0
        pf = abs(avg_w) / abs(avg_l) if avg_l != 0 else float('inf')
        print(f"\n{horizon}:")
        print(f"  Completed:     {len(valid)}")
        print(f"  Win Rate:      {wr:.1f}%")
        print(f"  Avg Win:       {avg_w:+.2f}%")
        print(f"  Avg Loss:      {avg_l:+.2f}%")
        print(f"  Profit Factor: {pf:.2f}")

    # By Setup
    if 'Setup' in df.columns:
        print("\n" + "=" * 60)
        print("BY SETUP (T+10)")
        print("=" * 60)
        for setup in ['BUY_A', 'BUY_B']:
            subset = df[df['Setup'] == setup]
            col = 'T+10_pct'
            if col not in subset.columns:
                continue
            valid = subset[col].dropna()
            if len(valid) == 0:
                continue
            wins = valid[valid > 0]
            losses = valid[valid <= 0]
            wr = len(wins) / len(valid) * 100
            avg_w = wins.mean() if len(wins) > 0 else 0
            avg_l = losses.mean() if len(losses) > 0 else 0
            print(f"\n{setup}: n={len(valid)}, WR={wr:.1f}%, "
                  f"AvgWin={avg_w:+.2f}%, AvgLoss={avg_l:+.2f}%")

    # By Vol Ratio
    if 'Vol Ratio' in df.columns:
        print("\n" + "=" * 60)
        print("BY VOL RATIO (T+10)")
        print("=" * 60)
        df['Vol_Ratio_num'] = df['Vol Ratio'].str.replace('x', '', regex=False).astype(float, errors='ignore')
        for label, subset in [('High Vol (>=2.0x)', df[df['Vol_Ratio_num'] >= 2.0]),
                               ('Low Vol (<2.0x)', df[df['Vol_Ratio_num'] < 2.0])]:
            col = 'T+10_pct'
            if col not in subset.columns:
                continue
            valid = subset[col].dropna()
            if len(valid) == 0:
                continue
            wins = valid[valid > 0]
            losses = valid[valid <= 0]
            wr = len(wins) / len(valid) * 100
            avg_w = wins.mean() if len(wins) > 0 else 0
            avg_l = losses.mean() if len(losses) > 0 else 0
            print(f"\n{label}: n={len(valid)}, WR={wr:.1f}%, "
                  f"AvgWin={avg_w:+.2f}%, AvgLoss={avg_l:+.2f}%")

    # By RSI
    if 'RSI' in df.columns:
        print("\n" + "=" * 60)
        print("BY RSI RANGE (T+10)")
        print("=" * 60)
        df['RSI_num'] = pd.to_numeric(df['RSI'], errors='coerce')
        for label, subset in [
            ('RSI < 30', df[df['RSI_num'] < 30]),
            ('RSI 30-40', df[(df['RSI_num'] >= 30) & (df['RSI_num'] < 40)]),
            ('RSI 40-50', df[(df['RSI_num'] >= 40) & (df['RSI_num'] < 50)]),
            ('RSI 50-60', df[(df['RSI_num'] >= 50) & (df['RSI_num'] < 60)]),
            ('RSI 60-70', df[(df['RSI_num'] >= 60) & (df['RSI_num'] < 70)]),
            ('RSI >= 70', df[df['RSI_num'] >= 70]),
        ]:
            col = 'T+10_pct'
            if col not in subset.columns:
                continue
            valid = subset[col].dropna()
            if len(valid) == 0:
                continue
            wins = valid[valid > 0]
            losses = valid[valid <= 0]
            wr = len(wins) / len(valid) * 100
            avg_w = wins.mean() if len(wins) > 0 else 0
            avg_l = losses.mean() if len(losses) > 0 else 0
            print(f"\n{label}: n={len(valid)}, WR={wr:.1f}%, "
                  f"AvgWin={avg_w:+.2f}%, AvgLoss={avg_l:+.2f}%")

    # Top/Bottom
    print("\n" + "=" * 60)
    print("TOP 10 WINNERS (T+10)")
    print("=" * 60)
    col = 'T+10_pct'
    if col in df.columns:
        for _, row in df.sort_values(col, ascending=False).head(10).iterrows():
            if pd.notna(row[col]):
                print(f"  {row.get('Date','')} {row.get('Ticker','')} ({row.get('Setup','')}): {row[col]:+.2f}%")

    print("\n" + "=" * 60)
    print("BOTTOM 10 LOSERS (T+10)")
    print("=" * 60)
    if col in df.columns:
        for _, row in df.sort_values(col, ascending=True).head(10).iterrows():
            if pd.notna(row[col]):
                print(f"  {row.get('Date','')} {row.get('Ticker','')} ({row.get('Setup','')}): {row[col]:+.2f}%")

    print("\n" + "=" * 60)
    print("ANALYSIS COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Screener retrospective analysis")
    parser.add_argument("--file", default="SignalTracker.md", help="Path to SignalTracker.md")
    args = parser.parse_args()

    df = load_tracker(args.file)
    if df is not None:
        analyze_patterns(df)