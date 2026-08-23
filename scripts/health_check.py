#!/usr/bin/env python3
"""
Health Check — Validates trading pipeline outputs for data quality.

Usage:
  python3 health_check.py tracker    # Check tracker file for staleness, NaN, errors
  python3 health_check.py summary    # Check summary exit code and row count
  python3 health_check.py brief      # Check brief file exists, signal count, tracker sync

Requirements:
  pip install pytz (optional — for timezone awareness)

Output:
  Prints health status. Exits non-zero if issues found.
  In production, this runs as a cron job after each main pipeline step.
"""

import os
import sys
import re
from datetime import datetime

try:
    import pytz
    TZ = pytz.timezone("America/Edmonton")
except ImportError:
    TZ = None

TRACKER_FILE = os.environ.get("SIGNAL_TRACKER_FILE", "SignalTracker.md")
BRIEF_DIR = os.environ.get("BRIEF_DIR", ".")
LOG_DIR = os.environ.get("LOG_DIR", "logs")


def now_mst():
    if TZ:
        return datetime.now(TZ)
    return datetime.now()


def read_exit(path):
    if not os.path.exists(path):
        return None
    with open(path, "r") as f:
        return f.read().strip()


def read_last_error(log_path):
    if not os.path.exists(log_path):
        return None
    keywords = ["Traceback", "Error:", "Exception", "YFRate", "ConnectionError", "ImportError"]
    try:
        with open(log_path, "r") as f:
            for line in reversed(f.readlines()):
                if any(k in line for k in keywords):
                    return line.strip()[:100]
    except:
        pass
    return None


def check_tracker():
    """Check tracker file: exit code, freshness, NaN count."""
    today = now_mst().strftime("%Y-%m-%d")
    time = now_mst().strftime("%H:%M")

    exit_val = read_exit(os.path.join(LOG_DIR, "tracker_last.exit"))
    exit_ok = exit_val == "0" if exit_val else False

    updated_today = False
    stale = False
    nan_count = 0

    if os.path.exists(TRACKER_FILE):
        mtime = os.path.getmtime(TRACKER_FILE)
        age_min = (datetime.now().timestamp() - mtime) / 60
        stale = age_min > 30
        with open(TRACKER_FILE, "r") as f:
            content = f.read()
            updated_today = today in content
            nan_count = content.lower().count("nan")

    error_line = read_last_error(os.path.join(LOG_DIR, "tracker_last.log"))

    print(f"Health Check — Tracker {today} {time}")
    print(f"  Exit: {'OK' if exit_ok else 'FAILED'}")
    if stale:
        print("  File: STALE (not modified in 30+ min)")
    elif updated_today:
        print("  File: Updated today")
    else:
        print("  File: Not updated today")
    if nan_count > 0:
        print(f"  WARNING: {nan_count} NaN values")
    if error_line:
        print(f"  Last error: {error_line}")

    if not exit_ok or stale or not updated_today:
        print("  STATUS: Manual check required")
        return 1
    print("  STATUS: OK")
    return 0


def check_summary():
    """Check summary exit code and tracker row count."""
    today = now_mst().strftime("%Y-%m-%d")
    exit_val = read_exit(os.path.join(LOG_DIR, "summary_last.exit"))
    exit_ok = exit_val == "0" if exit_val else False

    row_count = 0
    if os.path.exists(TRACKER_FILE):
        with open(TRACKER_FILE, "r") as f:
            row_count = len(re.findall(r'\|\s*\d{4}-\d{2}-\d{2}', f.read()))

    error_line = read_last_error(os.path.join(LOG_DIR, "summary_last.log"))

    print(f"Health Check — Summary {today}")
    print(f"  Exit: {'OK' if exit_ok else 'FAILED'}")
    print(f"  Tracker rows: {row_count}")
    if error_line:
        print(f"  Last error: {error_line}")

    return 0 if exit_ok else 1


def check_brief():
    """Check if today's brief was created and has signals."""
    today = now_mst().strftime("%Y-%m-%d")
    brief_path = os.path.join(BRIEF_DIR, f"{today}.md")

    if not os.path.exists(brief_path):
        print(f"Health Check — Brief {today}")
        print("  File: MISSING")
        return 1

    with open(brief_path, "r") as f:
        content = f.read()
    buy_a = len(re.findall(r'^### \S+ - BUY_A', content, re.MULTILINE))
    buy_b = len(re.findall(r'^### \S+ - BUY_B', content, re.MULTILINE))

    tracker_updated = False
    if os.path.exists(TRACKER_FILE):
        with open(TRACKER_FILE, "r") as f:
            tracker_updated = today in f.read()

    print(f"Health Check — Brief {today}")
    print(f"  File: Created")
    print(f"  Signals: BUY_A={buy_a}, BUY_B={buy_b}")
    print(f"  Tracker: {'Updated' if tracker_updated else 'NOT updated'}")

    return 0 if tracker_updated else 1


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "tracker":
        sys.exit(check_tracker())
    elif mode == "summary":
        sys.exit(check_summary())
    elif mode == "brief":
        sys.exit(check_brief())
    else:
        print("Usage: health_check.py [tracker|summary|brief]")
        sys.exit(1)