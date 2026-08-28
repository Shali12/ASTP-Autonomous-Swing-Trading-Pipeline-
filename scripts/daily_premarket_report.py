import os
import sys
import json
import re
import pytz
import requests
import yfinance as yf
import time
from datetime import datetime, timedelta
from dotenv import load_dotenv

#!/usr/bin/env python3
"""
Pre-Market Report — futures, VIX, sector ETFs, macro calendar and
Gemini-powered headline sentiment, posted daily before market open.

Sentiment call has one retry on upstream 5xx errors and degrades to
"Sentiment data unavailable" instead of failing the run.

Configuration (optional env vars):
  PREMARKET_REPORT_DIR  output directory for the daily .md report
  TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID  to post the report
  GEMINI_API_KEY        to enable headline sentiment

Requirements:
  pip install yfinance requests pytz
"""

# --- Configuration ---
try:
    from dotenv import load_dotenv
    load_dotenv()  # optional; plain env vars also work
except ImportError:
    pass
TZ = pytz.timezone("America/Edmonton")
OBSIDIAN_REPORT_DIR = os.environ.get("PREMARKET_REPORT_DIR", "premarket_reports")

# 2026 Fixed Macro Calendar (Sourced from federalreserve.gov and bls.gov)
MACRO_CALENDAR_2026 = {
    "2026-01-13": "CPI Release", "2026-01-28": "FOMC Decision",
    "2026-02-13": "CPI Release", "2026-03-11": "CPI Release",
    "2026-03-18": "FOMC Decision", "2026-04-10": "CPI Release",
    "2026-04-29": "FOMC Decision", "2026-05-12": "CPI Release",
    "2026-06-10": "CPI Release", "2026-06-17": "FOMC Decision",
    "2026-07-14": "CPI Release", "2026-07-29": "FOMC Decision",
    "2026-08-12": "CPI Release", "2026-09-11": "CPI Release",
    "2026-09-16": "FOMC Decision", "2026-10-14": "CPI Release",
    "2026-10-28": "FOMC Decision", "2026-11-10": "CPI Release",
    "2026-12-09": "FOMC Decision", "2026-12-10": "CPI Release",
}

def send_telegram(msg):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("Missing Telegram environment variables.")
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Failed to send Telegram message: {e}")

def get_market_data():
    results = {}
    indices = {"ES": "ES=F", "NQ": "NQ=F", "YM": "YM=F", "VIX": "^VIX"}
    for label, ticker in indices.items():
        try:
            t = yf.Ticker(ticker)
            fi = t.fast_info
            # FIX: yfinance's real fast_info keys are camelCase, not snake_case.
            # Confirmed directly: fi['last_price'] raises KeyError; fi['lastPrice'] works.
            curr = fi['lastPrice']
            prev = fi['previousClose']
            if label == "VIX":
                results[label] = f"{curr:.2f}"
            else:
                chg = (curr - prev) / prev * 100
                results[label] = f"{curr:.2f} ({chg:+.2f}%)"
        except Exception as e:
            # FIX: log the real reason, don't fail silently into an
            # unexplainable "N/A" that could persist for weeks unnoticed.
            print(f"Market data error for {label} ({ticker}): {e}")
            results[label] = "N/A"

    etfs = ["XLK", "XLF", "XLE", "XLY", "XLV"]
    etf_results = {}
    now_local = datetime.now(TZ)
    midnight_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)

    for ticker in etfs:
        try:
            t = yf.Ticker(ticker)
            # FIX: default interval on a 2-day pull is daily bars, which are
            # stamped once per session and can't distinguish "genuine fresh
            # pre-market tick" from "yesterday's row, not yet updated."
            # An intraday interval is required to make the Pre-Mkt/Last-Close
            # timestamp check mean anything.
            hist = t.history(period="1d", interval="5m", prepost=True)
            if hist.empty:
                etf_results[ticker] = "N/A"
                continue

            last_price = float(hist['Close'].iloc[-1])
            # Need a real previous-session close for the % change - a 1-day
            # intraday pull doesn't include it, so fetch it separately.
            daily = t.history(period="2d", interval="1d")
            prev_close = float(daily['Close'].iloc[-2]) if len(daily) >= 2 else last_price
            chg = (last_price - prev_close) / prev_close * 100 if prev_close else 0.0
            last_ts = hist.index[-1].astimezone(TZ)
            label = "Pre-Mkt" if last_ts >= midnight_local else "Last Close"
            etf_results[ticker] = f"{label}: {chg:+.2f}%"
        except Exception as e:
            print(f"Sector ETF error for {ticker}: {e}")
            etf_results[ticker] = "N/A"

    return results, etf_results

def get_macro_headlines():
    try:
        t_obj = yf.Ticker("SPY")
        news = t_obj.news
        if not news:
            return []
        
        headlines = []
        for item in news:
            content = item.get("content", {})
            title = content.get("title", "") or item.get("title", "")
            if title:
                headlines.append(title)
        return headlines
    except Exception as e:
        print(f"Error fetching headlines for SPY: {e}")
        return []

def get_macro_sentiment():
    gemini_key = os.environ.get("GEMINI_API_KEY")
    if not gemini_key:
        return "Sentiment data unavailable (API Key missing)"

    try:
        headlines = get_macro_headlines()
        headlines_text = "\n".join([f"- {h}" for h in headlines[:8]])

        prompt = f"""Analyze these macro-economic headlines for general market sentiment.
Some of these headlines are generic investment content, not real macro-economic or political news (ETF comparisons, single-stock hype, dividend strategy articles). Ignore those completely. Base your sentiment ONLY on headlines describing actual macro-economic events, geopolitical developments, or market-wide news. If none of the headlines qualify, say NEUTRAL - insufficient macro news today.

Headlines:
{headlines_text}

Reply with JSON only, no other text:
{{
  "sentiment": "BULLISH", "BEARISH", or "NEUTRAL",
  "reasoning": "one sentence max 12 words"
}}"""

        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-lite:generateContent?key={gemini_key}"
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        # One retry for transient upstream 5xx (e.g. Gemini 503 at 07:00 on 2026-08-28).
        for attempt in range(2):
            try:
                resp = requests.post(url, json=payload, timeout=15)
                resp.raise_for_status()
                break
            except requests.RequestException:
                if attempt == 1:
                    raise
                time.sleep(5)
        text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        text = re.sub(r'^```json\s*|\s*```$', '', text.strip(), flags=re.MULTILINE)
        data = json.loads(text)
        return f"{data['sentiment']} - {data['reasoning']}"

    except Exception as e:
        print(f"Sentiment Error: {e}")
        return "Sentiment data unavailable"

def main():
    now_local = datetime.now(TZ)
    today_str = now_local.strftime("%Y-%m-%d")

    mkt_data, etf_data = get_market_data()
    calendar_event = MACRO_CALENDAR_2026.get(today_str, "No major macro events")
    sentiment = get_macro_sentiment()

    report = f"🚀 PRE-MARKET REPORT — {today_str}\n"
    report += f"⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯\n"
    report += f"📈 FUTURES\nES: {mkt_data.get('ES')} | NQ: {mkt_data.get('NQ')} | YM: {mkt_data.get('YM')}\n"
    report += f"📉 VIX: {mkt_data.get('VIX')}\n\n"

    report += "🏗️ SECTORS\n"
    for ticker, val in etf_data.items():
        report += f"• {ticker}: {val}\n"

    report += f"\n📅 MACRO: {calendar_event}\n"
    report += f"📰 SENTIMENT: {sentiment}"

    send_telegram(report)

    os.makedirs(OBSIDIAN_REPORT_DIR, exist_ok=True)
    obsidian_path = f"{OBSIDIAN_REPORT_DIR}/{today_str}.md"
    with open(obsidian_path, "w") as f:
        f.write(f"# Pre-Market Report - {today_str}\n\n{report}")

if __name__ == "__main__":
    main()
