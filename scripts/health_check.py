#!/usr/bin/env python3
"""
Health Check — Validates trading pipeline outputs for data quality.

Usage:
  python3 health_check.py tracker    # Check tracker file for staleness, NaN, errors
  python3 health_check.py summary    # Check summary exit code and row count
  python3 health_check.py brief      # Check brief file exists, signal count, tracker sync

Configuration (all optional environment variables):
  SIGNAL_TRACKER_FILE  path to SignalTracker.md        (default: SignalTracker.md)
  BRIEF_DIR            directory of daily brief files  (default: briefs)
  TRADING_LOG_DIR      directory of *_last.exit/.log   (default: logs)
  TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID   if set, results are sent to Telegram
  ANTHROPIC_API_KEY or GEMINI_API_KEY    enables the optional LLM quality check

In production this runs as a cron job after each main pipeline step and
alerts via Telegram only when something is wrong (clean tracker/summary
runs stay silent). The brief check always reports so the daily brief
lands in the chat.

Signal detection tolerates flagged headers like:

    ### AAON 🚩 Catalyst - BUY_A

and ignores non-signal headers (e.g. '### 📊 Technical Audit for GME').
An LLM FAIL is overridden when deterministic checks find no real issue
(guards against LLM false positives on audit headers).

Requirements:
  pip install requests pytz python-dotenv (dotenv optional; env vars work alone)
"""
import os
import sys
import json
import re
import requests
import pytz
from datetime import datetime

TRACKER_FILE = os.environ.get("SIGNAL_TRACKER_FILE", "SignalTracker.md")
BRIEF_DIR = os.environ.get("BRIEF_DIR", "briefs")
LOG_DIR = os.environ.get("TRADING_LOG_DIR", "logs")


def send_telegram(msg):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("Missing Telegram environment variables.")
        print(f"Message would have been:\n{msg}")
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Failed to send Telegram message: {e}")
    print(f"SENT TO TELEGRAM:\n{msg}")


def llm_quality_check(brief_content):
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    gemini_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GEMINI_OUTREACH_KEY")

    system_prompt = "You are a quality checker for a stock screener output. Respond with valid JSON only. No other text."
    user_content = f"""Review this trading brief and reply with JSON only:
{{"status": "PASS" or "FAIL", "reason": "one sentence max 15 words"}}

FAIL if ANY of these are true:
- Zero lines matching the pattern '### TICKER - BUY_A' or '### TICKER - BUY_B'
- Any RSI value is below 0 or above 100
- Any price or volume ratio is 0 or negative
- The same ticker appears more than once AS A SIGNAL LINE 
  (i.e. more than one line matching '### TICKER - BUY_A' or 
  '### TICKER - BUY_B' with the same ticker symbol)

PASS if none of the above apply.
Brief content: {brief_content[:1500]}"""

    try:
        if anthropic_key:
            url = "https://api.anthropic.com/v1/messages"
            headers = {
                "x-api-key": anthropic_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json"
            }
            payload = {
                "model": "claude-3-haiku-20240307",
                "max_tokens": 100,
                "system": system_prompt,
                "messages": [{"role": "user", "content": user_content}]
            }
            resp = requests.post(url, headers=headers, json=payload, timeout=15)
            resp.raise_for_status()
            text = resp.json()["content"][0]["text"]
        elif gemini_key:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-lite:generateContent?key={gemini_key}"
            payload = {
                "contents": [{"parts": [{"text": f"{system_prompt}\n\n{user_content}"}]}]
            }
            resp = requests.post(url, json=payload, timeout=15)
            resp.raise_for_status()
            text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        else:
            return {"status": "UNKNOWN", "reason": "No API keys found"}

        return json.loads(text.strip().strip('`').replace('json', ''))
    except Exception as e:
        return {"status": "UNKNOWN", "reason": f"Error: {str(e)}"}


def deterministic_issues(content):
    """Deterministically check the LLM failure criteria. Returns a list of issue
    strings; empty list means clean. Guards against LLM false positives that
    count '### Technical Audit for TICKER' headers as signal lines."""
    from collections import Counter
    issues = []
    # Signal lines tolerate flags between ticker and verdict, e.g.
    # '### AAON 🚩 Catalyst - BUY_A'; audit headers have no '- BUY_x' suffix.
    sigs = re.findall(r'^### (\S+).*? - (?:BUY_A|BUY_B)$', content, re.MULTILINE)
    if len(sigs) == 0:
        issues.append("no signal lines")
    dups = [t for t, c in Counter(sigs).items() if c > 1]
    if dups:
        issues.append(f"duplicate signal lines: {dups}")
    # RSI range (headers and audit tables)
    for m in re.findall(r'RSI \(14\)\D*([\d.]+)', content):
        try:
            v = float(m)
            if v < 0 or v > 100:
                issues.append(f"RSI out of range: {v}")
        except ValueError:
            pass
    # Price / Volume Ratio must be positive
    for label, pat in (
        ("Price", r'Price\D*\$?([\d.]+)'),
        ("Volume Ratio", r'Volume Ratio\D*([\d.]+)'),
    ):
        for m in re.findall(pat, content):
            try:
                v = float(m)
                if v <= 0:
                    issues.append(f"{label} non-positive: {v}")
            except ValueError:
                pass
    return issues


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
            lines = f.readlines()
            for line in reversed(lines):
                if any(k in line for k in keywords):
                    return line.strip()[:100]
    except Exception:
        pass
    return None


def check_brief():
    tz = pytz.timezone("America/Edmonton")
    now_mst = datetime.now(tz)
    today_str = now_mst.strftime("%Y-%m-%d")
    current_time = now_mst.strftime("%H:%M")

    exit_val = read_exit(os.path.join(LOG_DIR, "brief_last.exit"))
    if exit_val is None:
        exit_ok, exit_note = False, "log missing (may not have run)"
    elif exit_val != "0":
        exit_ok, exit_note = False, f"exit code {exit_val}"
    else:
        exit_ok, exit_note = True, "OK"

    error_line = read_last_error(os.path.join(LOG_DIR, "brief_last.log"))

    brief_path = os.path.join(BRIEF_DIR, f"{today_str}.md")
    file_exists = os.path.exists(brief_path)
    file_note, buy_a, buy_b, eu_count, tracker_updated = "Missing", 0, 0, 0, False

    llm_status, llm_reason = "UNKNOWN", "N/A"

    if file_exists:
        size_kb = os.path.getsize(brief_path) / 1024
        mtime = os.path.getmtime(brief_path)
        age_min = (datetime.now() - datetime.fromtimestamp(mtime)).seconds / 60
        file_note = f"{size_kb:.1f} KB" + (" ⚠️ stale" if age_min > 30 else "")
        with open(brief_path, "r") as f:
            content = f.read()

        buy_a = len(re.findall(r'^### \S+.*? - BUY_A$', content, re.MULTILINE))
        buy_b = len(re.findall(r'^### \S+.*? - BUY_B$', content, re.MULTILINE))
        eu_count = content.count("Earnings Unknown")

        if os.path.exists(TRACKER_FILE):
            with open(TRACKER_FILE, "r") as f:
                tracker_updated = today_str in f.read()

        llm_res = llm_quality_check(content)
        llm_status = llm_res.get("status", "UNKNOWN")
        llm_reason = llm_res.get("reason", "No reason provided")

        # Override LLM FAIL when deterministic checks find no real issues.
        # Prevents recurring false alerts from the LLM misreading audit
        # headers (e.g. '### Technical Audit for MAT') as signal lines.
        if llm_status == "FAIL":
            di = deterministic_issues(content)
            if not di:
                llm_status = "PASS"
                llm_reason = ("LLM FAIL overridden — deterministic check found "
                              "no duplicate/RSI/price issues (false positive)")

    lines = [f"🏥 Health Check — Brief {today_str} {current_time} MST"]
    lines.append(f"Exit: {'✅ OK' if exit_ok else f'❌ FAILED ({exit_note})'}")
    lines.append(f"File: {'✅ Created (' + file_note + ')' if file_exists else '❌ Missing'}")
    if file_exists:
        lines.append(f"Signals: BUY_A: {buy_a} | BUY_B: {buy_b}")
    if eu_count > 0:
        lines.append(f"Earnings Unknown: ⚠️ {eu_count} flags")
    if file_exists:
        lines.append(f"SignalTracker: {'✅ Updated' if tracker_updated else '⚠️ Not updated'}")

    llm_icon = "✅ PASS" if llm_status == "PASS" else "⚠️ FAIL" if llm_status == "FAIL" else "❓ UNKNOWN"
    lines.append(f"LLM Check: {llm_icon} — {llm_reason}")

    if error_line:
        lines.append(f"Last error: {error_line}")

    any_fail = not exit_ok or not file_exists or (file_exists and not tracker_updated) or (llm_status == "FAIL")
    if any_fail:
        lines.append("⚠️ Manual check required")

    # Brief: always post results (OK or not) so the daily brief lands on Telegram.
    send_telegram("\n".join(lines))


def check_tracker():
    tz = pytz.timezone("America/Edmonton")
    now_mst = datetime.now(tz)
    today_str = now_mst.strftime("%Y-%m-%d")
    current_time = now_mst.strftime("%H:%M")

    exit_val = read_exit(os.path.join(LOG_DIR, "tracker_last.exit"))
    if exit_val is None:
        exit_ok, exit_note = False, "log missing"
    elif exit_val != "0":
        exit_ok, exit_note = False, f"exit code {exit_val}"
    else:
        exit_ok, exit_note = True, "OK"

    error_line = read_last_error(os.path.join(LOG_DIR, "tracker_last.log"))

    updated_today, stale, nan_count = False, False, 0
    if os.path.exists(TRACKER_FILE):
        mtime = os.path.getmtime(TRACKER_FILE)
        age_min = (datetime.now() - datetime.fromtimestamp(mtime)).seconds / 60
        stale = age_min > 30
        with open(TRACKER_FILE, "r") as f:
            content = f.read()
            updated_today = today_str in content
            nan_count = content.lower().count("nan")

    lines = [f"🏥 Health Check — Tracker {today_str} {current_time} MST"]
    lines.append(f"Exit: {'✅ OK' if exit_ok else f'❌ FAILED ({exit_note})'}")
    if stale:
        lines.append("File: ❌ Stale (not modified in 30+ min)")
    elif updated_today:
        lines.append("File: ✅ Updated today")
    else:
        lines.append("File: ⚠️ Not updated today")
    if nan_count > 0:
        lines.append(f"⚠️ {nan_count} NaN values in tracker")
    if error_line:
        lines.append(f"Last error: {error_line}")
    any_fail = not exit_ok or stale or not updated_today
    if any_fail:
        lines.append("⚠️ Manual check required")
        send_telegram("\n".join(lines))
    # else: clean run — emit nothing, cron stays silent


def check_summary():
    tz = pytz.timezone("America/Edmonton")
    now_mst = datetime.now(tz)
    today_str = now_mst.strftime("%Y-%m-%d")
    current_time = now_mst.strftime("%H:%M")

    exit_val = read_exit(os.path.join(LOG_DIR, "summary_last.exit"))
    if exit_val is None:
        exit_ok, exit_note = False, "log missing"
    elif exit_val != "0":
        exit_ok, exit_note = False, f"exit code {exit_val}"
    else:
        exit_ok, exit_note = True, "OK"

    error_line = read_last_error(os.path.join(LOG_DIR, "summary_last.log"))

    row_count = 0
    if os.path.exists(TRACKER_FILE):
        with open(TRACKER_FILE, "r") as f:
            row_count = len(re.findall(r'\|\s*\d{4}-\d{2}-\d{2}', f.read()))

    lines = [f"🏥 Health Check — Summary {today_str} {current_time} MST"]
    lines.append(f"Exit: {'✅ OK' if exit_ok else f'❌ FAILED ({exit_note})'}")
    lines.append(f"Tracker rows: {row_count}")
    if error_line:
        lines.append(f"Last error: {error_line}")
    if not exit_ok:
        lines.append("⚠️ Manual check required")
        send_telegram("\n".join(lines))
    # else: clean run — emit nothing, cron stays silent


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "brief":
        check_brief()
    elif mode == "tracker":
        check_tracker()
    elif mode == "summary":
        check_summary()
    else:
        print("Usage: health_check.py [brief|tracker|summary]")
