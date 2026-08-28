#!/usr/bin/env python3
"""
Validation Progress Watcher — tracks whether the self-validation loop is
actually moving toward verdicts.

For every change in review_recommendations.json, counts post-change signals
in SignalTracker.md:
  logged     = table rows dated on/after the change date
  completed  = those rows with a WIN/LOSS T+10 Outcome filled

State is persisted to a JSON file (VALIDATION_PROGRESS_STATE env var). The
script prints ONLY when something changed since the last run (new post-change
signal, a completion, a milestone, or stagnation) — silent otherwise, so a
daily cron stays quiet until there is news.

Milestones printed:
  - VALIDATION READY      first change reaches 15+ completed post-change signals
  - STAGNATION ALERT      no new post-change signal for 3+ trading days
  - T+10 completion window dates for the current post-change cohort

Configuration (optional env vars):
  SIGNAL_TRACKER_FILE           path to SignalTracker.md
  REVIEW_RECOMMENDATIONS_FILE   path to review_recommendations.json
  VALIDATION_PROGRESS_STATE     path to the progress state file
  TIMEZONE                      IANA timezone (default: America/Edmonton)

Usage: python3 validation_progress.py
"""
import json
import os
import sys
from datetime import datetime, timedelta

import pytz


def _d(s):
    return datetime.strptime(s, "%Y-%m-%d").date()


def busday_count(start, end):
    """Business days (Mon-Fri) in [start, end). Same semantics as np.busday_count."""
    if end <= start:
        return 0
    n, d = 0, _d(start)
    stop = _d(end)
    while d < stop:
        if d.weekday() < 5:
            n += 1
        d += timedelta(days=1)
    return n


def busday_offset(date_str, days):
    """N business days after date_str (weekend dates roll forward). Same as
    np.busday_offset(date, n, roll='forward')."""
    d = _d(date_str)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    added = 0
    while added < days:
        d += timedelta(days=1)
        if d.weekday() < 5:
            added += 1
    return d.isoformat()
TZ = pytz.timezone(os.environ.get("TIMEZONE", "America/Edmonton"))
TRACKER = os.environ.get("SIGNAL_TRACKER_FILE", "SignalTracker.md")
RECS = os.environ.get("REVIEW_RECOMMENDATIONS_FILE", "review_recommendations.json")
STATE = os.environ.get("VALIDATION_PROGRESS_STATE", "validation_progress.json")
TARGET = 15
STAGNATION_TRADING_DAYS = 3


def find_table(lines):
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith("|") and ("Signal Date" in s or "Date" in s):
            return i
    return None


def tracker_rows():
    """Return (date_str, completed_bool) for every signal row in the table."""
    if not os.path.exists(TRACKER):
        return []
    with open(TRACKER) as f:
        lines = f.readlines()
    hidx = find_table(lines)
    if hidx is None:
        return []
    rows = []
    for line in lines[hidx + 2:]:
        s = line.strip()
        if not s.startswith("|"):
            continue
        parts = s.split("|")
        if parts and not parts[0]:
            parts = parts[1:]
        if parts and not parts[-1]:
            parts = parts[:-1]
        if len(parts) < 2:
            continue
        date_str = parts[0].strip()
        outcome = parts[14].strip() if len(parts) > 14 else ""
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            continue
        rows.append((date_str, "WIN" in outcome.upper() or "LOSS" in outcome.upper()))
    return rows


def main():
    if not os.path.exists(RECS):
        print(f"VALIDATION WATCH ERROR: recommendations file missing: {RECS}")
        sys.exit(1)
    if not os.path.exists(TRACKER):
        print(f"VALIDATION WATCH ERROR: tracker file missing: {TRACKER}")
        sys.exit(1)
    with open(RECS) as f:
        recs = json.load(f)

    rows = tracker_rows()
    today = datetime.now(TZ).strftime("%Y-%m-%d")

    per_change = []
    all_post_dates = []
    for rec in recs.get("changes", []):
        cd = rec.get("date")
        if not cd:
            continue
        post = [(d, done) for d, done in rows if d >= cd]
        per_change.append({
            "date": cd,
            "filter": rec.get("filter", ""),
            "desc": rec.get("description", "")[:60],
            "logged": len(post),
            "completed": sum(1 for _, done in post if done),
        })
        all_post_dates.extend(d for d, _ in post)

    latest_post = max(all_post_dates) if all_post_dates else None
    stagnant_days = busday_count(latest_post, today) if latest_post else 999

    # completion window for the current cohort (T+10 trading days)
    if all_post_dates:
        window = f"{busday_offset(min(all_post_dates), 10)} to {busday_offset(max(all_post_dates), 10)}"
    else:
        window = "no post-change signals yet"

    snapshot = {
        "date": str(today),
        "total_post_logged": sum(c["logged"] for c in per_change),
        "total_post_completed": sum(c["completed"] for c in per_change),
        "stagnant_days": stagnant_days,
        "per_change": per_change,
        "window": window,
    }

    prev = None
    if os.path.exists(STATE):
        try:
            with open(STATE) as f:
                prev = json.load(f)
        except Exception:
            prev = None

    # Build the report we WOULD print
    lines = [f"🔍 Validation progress — {snapshot['date']} MST",
             f"Post-change signals: {snapshot['total_post_logged']} logged, "
             f"{snapshot['total_post_completed']}/{TARGET} completed (verdict needs {TARGET}+)",
             f"T+10 completion window for current cohort: {window}"]
    for c in per_change:
        lines.append(f"  • [{c['date']}] {c['desc']}: logged {c['logged']}, completed {c['completed']}")
    if stagnant_days >= STAGNATION_TRADING_DAYS:
        lines.append(f"⚠️ STAGNATION ALERT: no new post-change signal in {stagnant_days} trading days")
    ready = [c for c in per_change if c["completed"] >= TARGET]
    if ready:
        lines.append(f"✅ VALIDATION READY: {len(ready)} change(s) have {TARGET}+ completed signals — "
                     f"next 48h review cycle will issue verdicts")

    # Print only on change (or first run baseline)
    changed = (prev is None
               or prev.get("total_post_logged") != snapshot["total_post_logged"]
               or prev.get("total_post_completed") != snapshot["total_post_completed"]
               or prev.get("stagnant_days") != snapshot["stagnant_days"]
               or prev.get("window") != snapshot["window"])

    if changed:
        if prev is None:
            lines.insert(1, "(baseline established — silent from here until something changes)")
        print("\n".join(lines))

    with open(STATE, "w") as f:
        json.dump(snapshot, f, indent=2)


if __name__ == "__main__":
    main()
