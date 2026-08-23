#!/usr/bin/env python3
"""
Self-Validation Script — Validates prior improvement cycle recommendations.

Usage:
  python3 review_validation.py                          # Uses default paths
  python3 review_validation.py --signals path/to/data.md
  python3 review_validation.py --recommendations path/to/recs.json

Requirements:
  pip install pandas numpy

Output:
  Prints validation results — whether prior strategy changes improved
  win rate, regressed it, or still need more data to evaluate.
"""

import os
import json
import argparse
from datetime import datetime

import pandas as pd
import numpy as np


def _find_table(lines):
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith("|") and ("Date" in s or "Ticker" in s or "Signal Date" in s):
            return i
    return None


def parse_signal_tracker(filepath):
    """Parse completed WIN/LOSS signals from SignalTracker.md."""
    if not os.path.exists(filepath):
        return []
    with open(filepath) as f:
        lines = f.readlines()
    hidx = _find_table(lines)
    if hidx is None:
        return []

    def parse_outcome(o):
        u = o.upper()
        if "WIN" in u: return True
        if "LOSS" in u: return False
        return None

    signals = []
    for line in lines[hidx + 2:]:
        s = line.strip()
        if not s or not s.startswith("|"):
            continue
        cols = [c.strip() for c in s.split('|') if c.strip()]
        if len(cols) < 15:
            continue
        res = parse_outcome(cols[14])
        if res is None:
            continue
        try:
            rsi = float(cols[5])
        except:
            rsi = None
        try:
            vol = float(cols[6].replace('x', '').replace('X', ''))
        except:
            vol = None
        try:
            sdate = datetime.strptime(cols[0].strip(), "%Y-%m-%d")
        except:
            sdate = None
        signals.append({
            'date': sdate, 'setup': cols[2].strip(), 'win': res,
            'rsi': rsi, 'vol': vol
        })
    return signals


def run_validation(signals, recommendations):
    """Compare win rates before/after each recommendation's change date."""
    results = {}
    for rec in recommendations.get('changes', []):
        change_date = rec.get('date')
        if not change_date:
            continue
        try:
            cd = datetime.strptime(change_date, "%Y-%m-%d")
        except:
            continue

        pre = [s for s in signals if s['date'] and s['date'] < cd]
        post = [s for s in signals if s['date'] and s['date'] >= cd]

        if len(pre) < 15 or len(post) < 15:
            results[rec.get('description', 'unknown')] = {
                'status': 'insufficient_sample',
                'pre_n': len(pre), 'post_n': len(post),
                'note': f'Need 15+ signals each side of {change_date}'
            }
            continue

        def wr(sub):
            n = len(sub)
            return sum(1 for s in sub if s['win']) / n * 100 if n > 0 else 0

        filter_key = rec.get('filter', '')
        if filter_key == 'rsi_lt_55':
            pre_f = [s for s in pre if s['rsi'] and s['rsi'] < 55]
            post_f = [s for s in post if s['rsi'] and s['rsi'] < 55]
        elif filter_key == 'vol_lt_2':
            pre_f = [s for s in pre if s['vol'] and s['vol'] < 2.0]
            post_f = [s for s in post if s['vol'] and s['vol'] < 2.0]
        else:
            pre_f = pre
            post_f = post

        pre_wr = wr(pre)
        post_wr = wr(post)
        pre_f_wr = wr(pre_f) if pre_f else 0
        post_f_wr = wr(post_f) if post_f else 0
        improved = post_f_wr > pre_f_wr + 2.0

        results[rec.get('description', 'unknown')] = {
            'status': 'improved' if improved else 'no_improvement',
            'pre_wr': round(pre_wr, 1),
            'post_wr': round(post_wr, 1),
            'pre_filtered_wr': round(pre_f_wr, 1),
            'post_filtered_wr': round(post_f_wr, 1),
            'pre_n': len(pre), 'post_n': len(post),
            'change_date': change_date,
            'action': 'keep' if improved else 'revert'
        }
    return results


def main():
    parser = argparse.ArgumentParser(description="Self-validation for improvement cycle")
    parser.add_argument("--signals", default="SignalTracker.md", help="Path to SignalTracker.md")
    parser.add_argument("--recommendations", default="review_recommendations.json",
                        help="Path to recommendations JSON")
    args = parser.parse_args()

    # Load recommendations
    recs = {}
    if os.path.exists(args.recommendations):
        with open(args.recommendations) as f:
            recs = json.load(f)

    signals = parse_signal_tracker(args.signals)
    validation = run_validation(signals, recs)

    print("=" * 60)
    print("IMPROVEMENT VALIDATION")
    print("=" * 60)
    print(f"Total completed signals: {len(signals)}")
    print()
    for k, v in validation.items():
        status = v['status']
        action = v.get('action', 'N/A')
        print(f"  {k}: {status} -> {action}")
        for key, val in v.items():
            if key not in ('status', 'action'):
                print(f"    {key}: {val}")
    print("=" * 60)


if __name__ == "__main__":
    main()