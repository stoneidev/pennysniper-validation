"""
Daily scanner: detects breakout signals based on the CURRENT QUARTER's rule.

Usage (cron):
  # Every weekday 5pm KST (after US market close)
  0 17 * * 1-5  cd /path/to/repo && python scripts/live/daily_scanner.py

What it does:
  1. Reads current quarter's rule from config/current_rule.json
  2. Loads latest Stooq daily data from STOOQ_DIR
  3. Finds today's breakout signals
  4. Appends to logs/signals_YYYY-MM.csv
  5. Prints alert (can be wired to Telegram/Slack/email)

Config file (config/current_rule.json) must contain:
  {
    "cons_d": 30,
    "entry_lo": 1.20,
    "entry_hi": 1.50,
    "tp_ratio": 1.15,
    "hold_d": 30,
    "valid_until": "2026-09-30"
  }
"""
import json
import sys
from pathlib import Path
from datetime import date
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
STOOQ_DIR = Path("/Users/stoni/Downloads/data/daily/us/nasdaq stocks")
CONFIG = REPO / "config" / "current_rule.json"
LOGS = REPO / "logs"
LOGS.mkdir(exist_ok=True)
(REPO / "config").mkdir(exist_ok=True)

MIN_AVG_VOL = 10_000
EXCLUDE_SUFFIX = ("W", "R", "U", "Z")


def load_rule():
    if not CONFIG.exists():
        print(f"ERROR: {CONFIG} missing.", file=sys.stderr)
        print("Create it via scripts/live/quarterly_retrain.py")
        sys.exit(1)
    with open(CONFIG) as f:
        rule = json.load(f)
    if "valid_until" in rule:
        valid_until = pd.Timestamp(rule["valid_until"])
        if pd.Timestamp.now() > valid_until:
            print(f"WARNING: rule expired on {valid_until.date()}. Re-run quarterly_retrain.py")
    return rule


def is_excluded(s):
    if s.endswith(EXCLUDE_SUFFIX):
        return True
    if len(s) > 4 and s[-3:].startswith("PR"):
        return True
    return False


def parse_csv(path):
    try:
        df = pd.read_csv(path)
    except Exception:
        return None
    if df.empty or "<DATE>" not in df.columns:
        return None
    df = df.rename(columns={
        "<DATE>": "date", "<OPEN>": "Open", "<HIGH>": "High",
        "<LOW>": "Low", "<CLOSE>": "Close", "<VOL>": "Volume",
    })
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    if len(df) < 65:
        return None
    return df.sort_values("date").reset_index(drop=True)


def detect_signals(rule):
    cons_d = rule["cons_d"]
    entry_lo = rule["entry_lo"]
    entry_hi = rule["entry_hi"]
    tp_ratio = rule["tp_ratio"]
    hold_d = rule["hold_d"]

    csv_files = []
    for d in STOOQ_DIR.iterdir():
        if d.is_dir():
            csv_files.extend(d.glob("*.txt"))

    signals = []
    today = pd.Timestamp.now().normalize()

    for f in csv_files:
        sym = f.stem.upper().replace(".US", "")
        if is_excluded(sym):
            continue
        df = parse_csv(f)
        if df is None or len(df) < cons_d + 2:
            continue

        # Last bar = today's close
        last = df.iloc[-1]
        prev = df.iloc[-2] if len(df) >= 2 else None
        last_close = float(last["Close"])
        prev_close = float(prev["Close"]) if prev is not None else None

        # Check breakout condition on LATEST bar
        if not (entry_lo <= last_close < entry_hi):
            continue
        if prev_close is not None and prev_close >= entry_lo:
            continue

        # Check 60d/30d/etc consolidation BEFORE this last bar
        prior = df["Close"].values[-(cons_d + 1):-1]
        if len(prior) < cons_d:
            continue
        if not (prior < 1.0).all() or not (prior > 0).all():
            continue
        if df["Volume"].values[-(cons_d + 1):-1].mean() < MIN_AVG_VOL:
            continue

        # Plan trade: enter NEXT day open
        signals.append({
            "scanner_date": today.strftime("%Y-%m-%d"),
            "data_last_date": last["date"].strftime("%Y-%m-%d"),
            "symbol": sym,
            "today_close": last_close,
            "prev_close": prev_close,
            "tp_target_ratio": tp_ratio,
            "hold_days": hold_d,
            "rule_cons_d": cons_d,
            "rule_entry_lo": entry_lo,
            "rule_entry_hi": entry_hi,
        })

    return signals


def main():
    rule = load_rule()
    print(f"Current rule: cons {rule['cons_d']}d / entry [${rule['entry_lo']:.2f}, ${rule['entry_hi']:.2f}) "
          f"/ TP +{(rule['tp_ratio']-1)*100:.0f}% / hold {rule['hold_d']}d")
    print(f"Valid until: {rule.get('valid_until', 'N/A')}")
    print()

    signals = detect_signals(rule)
    if not signals:
        print("No new signals today.")
        return

    print(f"🚨 {len(signals)} NEW SIGNAL(S):\n")
    for s in signals:
        target = s["today_close"] * s["tp_target_ratio"]
        print(f"  {s['symbol']:<8} (data {s['data_last_date']})")
        print(f"    today close: ${s['today_close']:.2f}")
        print(f"    plan: BUY at next-day open, TP ${target:.2f} (+{(s['tp_target_ratio']-1)*100:.0f}%), max hold {s['hold_days']}d")
        print()

    # Append to log
    log_file = LOGS / f"signals_{pd.Timestamp.now().strftime('%Y-%m')}.csv"
    df = pd.DataFrame(signals)
    if log_file.exists():
        df.to_csv(log_file, mode="a", index=False, header=False)
    else:
        df.to_csv(log_file, index=False)
    print(f"Appended to {log_file}")


if __name__ == "__main__":
    main()
