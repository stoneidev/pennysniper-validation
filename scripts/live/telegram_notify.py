"""
Telegram notifier for daily breakout scanner.

Sends a Telegram message after each daily scan:
  - Always sends a one-line "scan done" summary
  - If signals found, sends a detailed alert with symbols + TP targets + report link

Required env vars:
  TELEGRAM_BOT_TOKEN  (e.g., 8792335276:AAE_sw...)
  TELEGRAM_CHAT_ID    (numeric chat id)

Usage:
  python scripts/live/telegram_notify.py [--as-of YYYY-MM-DD]

If TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is missing, exits silently
(GH Action can run without secrets configured during initial setup).
"""
import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path
import re
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
REPORTS = REPO / "reports"
CONFIG = REPO / "config" / "current_rule.json"

PAGES_BASE = "https://stoneidev.github.io/pennysniper-validation"


def send_message(text: str, parse_mode: str = "HTML"):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("WARN: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set — skipping send.")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": "false",
    }).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        if body.get("ok"):
            print(f"Telegram message sent (msg_id={body['result']['message_id']})")
            return True
        print(f"Telegram API error: {body}")
        return False
    except Exception as e:
        print(f"Telegram send failed: {e}")
        return False


def parse_signals_from_report(report_path: Path):
    """Extract symbols + today_close + tp_target from a daily HTML report."""
    if not report_path.exists():
        return []
    text = report_path.read_text(encoding="utf-8")
    rows = re.findall(
        r'<td class="sym">([A-Z]+)</td>\s*'
        r'<td class="num">\$([\d.]+)</td>\s*'
        r'<td class="num">\$([\d.]+)</td>\s*'
        r'<td class="num">\$([\d.]+)</td>\s*'
        r'<td class="num target">\$([\d.]+)</td>',
        text,
    )
    return [
        {"symbol": s, "today_close": float(t), "prev_close": float(p),
         "consolidation_avg": float(c), "tp_target": float(tp)}
        for s, t, p, c, tp in rows
    ]


def build_message(date_str: str, signals: list, rule: dict | None) -> str:
    """Build HTML-formatted Telegram message."""
    pages_url = f"{PAGES_BASE}/{date_str}.html"
    repo_url = f"https://github.com/stoneidev/pennysniper-validation"

    if not signals:
        text = (
            f"<b>✅ Daily scan done</b> — 0 signals\n"
            f"<i>{date_str}</i>"
        )
        if rule:
            text += (
                f"\n\nRule in effect:\n"
                f"<code>{rule['cons_d']}d / "
                f"${rule['entry_lo']:.2f}-${rule['entry_hi']:.2f} / "
                f"+{(rule['tp_ratio']-1)*100:.0f}% / "
                f"{rule['hold_d']}d</code>"
            )
        text += f"\n\n<a href='{pages_url}'>📄 Today's report</a>"
        return text

    # With signals
    lines = [f"<b>🎯 PennySniper Signal Alert</b>",
             f"<i>{date_str}</i>",
             ""]

    if rule:
        lines.append(
            f"Rule: <code>{rule['cons_d']}d / "
            f"${rule['entry_lo']:.2f}-${rule['entry_hi']:.2f} / "
            f"+{(rule['tp_ratio']-1)*100:.0f}% / "
            f"{rule['hold_d']}d</code>"
        )
        lines.append("")

    lines.append(f"<b>NEW SIGNALS ({len(signals)})</b>:")
    for s in signals:
        lines.append(
            f"• <b>{s['symbol']}</b> @ ${s['today_close']:.2f} "
            f"→ TP ${s['tp_target']:.2f} "
            f"(+{(s['tp_target']/s['today_close']-1)*100:.0f}%)"
        )
    lines.append("")
    lines.append("Plan: BUY next-day open, sell at TP target, max-hold timer per rule.")
    lines.append("")
    lines.append(f"<a href='{pages_url}'>📄 Daily report</a>  ·  <a href='{PAGES_BASE}'>🌐 Index</a>")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--as-of", help="Date YYYY-MM-DD (default: today)")
    args = parser.parse_args()

    as_of = pd.Timestamp(args.as_of) if args.as_of else pd.Timestamp.now().normalize()
    date_str = as_of.strftime("%Y-%m-%d")

    rule = json.load(open(CONFIG)) if CONFIG.exists() else None
    report_path = REPORTS / f"{date_str}.html"
    signals = parse_signals_from_report(report_path)

    msg = build_message(date_str, signals, rule)
    print("=== Message preview ===")
    print(msg)
    print("=== End preview ===\n")

    ok = send_message(msg)
    if not ok:
        sys.exit(0)  # don't fail the workflow if Telegram fails


if __name__ == "__main__":
    main()
