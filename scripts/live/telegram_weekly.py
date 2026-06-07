"""
Telegram notifier for weekly insight report.

Sends a Telegram summary every Saturday after weekly_report.py runs.
Includes: this-week stats, regime tag, cumulative win/return, link to report.
"""
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
REPORTS = REPO / "reports"
CONFIG = REPO / "config" / "current_rule.json"
PAGES_BASE = "https://stoneidev.github.io/pennysniper-validation"


def send_message(text: str):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("WARN: Telegram secrets missing, skipping send.")
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": "false",
    }).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        if body.get("ok"):
            print(f"Sent (msg_id={body['result']['message_id']})")
            return True
        print(f"API error: {body}")
        return False
    except Exception as e:
        print(f"Send failed: {e}")
        return False


def main():
    today = pd.Timestamp.now().normalize()
    iso_year, iso_week, _ = today.isocalendar()
    weekly_path = REPORTS / f"_weekly_{iso_year}-W{iso_week:02d}.html"

    if not weekly_path.exists():
        print(f"No weekly report at {weekly_path} — nothing to send.")
        return

    text = weekly_path.read_text(encoding="utf-8")

    # Extract aggregate stats from the weekly HTML (best-effort)
    def extract(pattern):
        m = re.search(pattern, text)
        return m.group(1) if m else None

    # This-week
    this_week_signals = extract(r'<div class="label">Signals fired</div>\s*<div class="value">(\d+)</div>')
    this_week_winrate = extract(r'<div class="label">Win rate</div>\s*<div class="value[^"]*">([^<]+)</div>')
    this_week_mean = extract(r'<div class="label">Mean net return</div>\s*<div class="value[^"]*">([^<]+)</div>')

    # Cumulative
    cum_signals = extract(r'<h2>Cumulative.*?</h2>.*?<div class="label">Total signals</div>\s*<div class="value">(\d+)</div>')
    cum_winrate = extract(r'<div class="label">Cumulative win rate</div>\s*<div class="value[^"]*">([^<]+)</div>')
    cum_capital = extract(r'<div class="label">₩1M \(25% allocation\)</div>\s*<div class="value[^"]*">([^<]+)</div>')

    # Regime
    regime = extract(r'<span class="pill (?:green|yellow|red|muted)">([^<]+)</span>')

    # Active rule
    rule = None
    if CONFIG.exists():
        rule = json.load(open(CONFIG))

    pages_url = f"{PAGES_BASE}/_weekly_{iso_year}-W{iso_week:02d}.html"

    # Build message
    lines = [
        f"<b>📊 PennySniper Weekly Report</b>",
        f"<i>{iso_year} W{iso_week:02d} ({today.strftime('%Y-%m-%d')})</i>",
        "",
    ]
    if regime:
        lines.append(f"<b>Regime:</b> {regime}")
        lines.append("")

    lines.append("<b>This week</b>")
    if this_week_signals is not None:
        lines.append(f"  Signals fired: <b>{this_week_signals}</b>")
    if this_week_winrate:
        lines.append(f"  Win rate: <b>{this_week_winrate}</b>")
    if this_week_mean:
        lines.append(f"  Mean return: <b>{this_week_mean}</b>")
    lines.append("")

    lines.append("<b>Cumulative</b>")
    if cum_signals:
        lines.append(f"  Total signals: <b>{cum_signals}</b>")
    if cum_winrate:
        lines.append(f"  Win rate: <b>{cum_winrate}</b>")
    if cum_capital:
        lines.append(f"  ₩1M (25% alloc) → <b>{cum_capital}</b>")
    lines.append("")

    if rule:
        lines.append(f"Active rule: <code>{rule['cons_d']}d / "
                     f"${rule['entry_lo']:.2f}-${rule['entry_hi']:.2f} / "
                     f"+{(rule['tp_ratio']-1)*100:.0f}% / "
                     f"{rule['hold_d']}d</code>")
        lines.append("")

    lines.append(f"<a href='{pages_url}'>📈 Full weekly report</a>  ·  "
                 f"<a href='{PAGES_BASE}/_positions.html'>💼 Positions</a>")

    msg = "\n".join(lines)
    print("=== Message ===")
    print(msg)
    print("===============\n")

    send_message(msg)


if __name__ == "__main__":
    main()
