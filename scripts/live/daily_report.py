"""
Daily breakout signal scanner + markdown report generator.

Reads:
  data/daily_cache/{TICKER}.csv  (from fetch_universe.py)
  config/current_rule.json      (from quarterly_retrain.py)

Outputs:
  reports/YYYY-MM-DD.md          (one report per day)
  reports/_index.md              (index of all reports)

For a specific historical date, use --as-of YYYY-MM-DD. The scanner uses
data ONLY up to that date — no look-ahead.
"""
import json
import argparse
from pathlib import Path
import pandas as pd
import numpy as np

REPO = Path(__file__).resolve().parents[2]
CACHE = REPO / "data" / "daily_cache"
CONFIG = REPO / "config" / "current_rule.json"
REPORTS = REPO / "reports"
REPORTS.mkdir(exist_ok=True)

MIN_AVG_VOL = 10_000


def parse_csv(path):
    try:
        df = pd.read_csv(path, parse_dates=["Date"])
    except Exception:
        return None
    if df.empty or len(df) < 35:
        return None
    return df.sort_values("Date").reset_index(drop=True)


def detect_signals(rule: dict, as_of: pd.Timestamp):
    """Find all signals where the breakout day is the latest bar at-or-before as_of."""
    cons_d = rule["cons_d"]
    entry_lo = rule["entry_lo"]
    entry_hi = rule["entry_hi"]

    csv_files = sorted(CACHE.glob("*.csv"))
    csv_files = [f for f in csv_files if not f.name.startswith("_")]
    signals = []

    for f in csv_files:
        sym = f.stem
        df = parse_csv(f)
        if df is None:
            continue
        # Trim to as_of (no look-ahead)
        df = df[df["Date"] <= as_of].reset_index(drop=True)
        if len(df) < cons_d + 2:
            continue

        # The signal is detected on the last bar of df (which is as_of or the most recent trading day).
        last = df.iloc[-1]
        if last["Date"] != as_of:
            # Allow for weekends/holidays — accept if last trading bar is within 4 days of as_of
            if (as_of - last["Date"]).days > 4:
                continue
        prev = df.iloc[-2] if len(df) >= 2 else None
        last_close = float(last["Close"])
        prev_close = float(prev["Close"]) if prev is not None else None

        if not (entry_lo <= last_close < entry_hi):
            continue
        if prev_close is None or prev_close >= entry_lo:
            continue

        prior = df["Close"].values[-(cons_d + 1):-1]
        if len(prior) < cons_d:
            continue
        if not (prior < 1.0).all() or not (prior > 0).all():
            continue
        if df["Volume"].values[-(cons_d + 1):-1].mean() < MIN_AVG_VOL:
            continue

        signals.append({
            "symbol": sym,
            "signal_date": last["Date"].strftime("%Y-%m-%d"),
            "today_close": last_close,
            "prev_close": prev_close,
            "consolidation_avg": float(prior.mean()),
            "consolidation_avg_vol": float(df["Volume"].values[-(cons_d + 1):-1].mean()),
        })

    return signals


def render_report(rule, as_of, signals, out_path):
    target_ratio = rule["tp_ratio"]
    hold_d = rule["hold_d"]

    lines = []
    lines.append(f"# Breakout Daily Report — {as_of.strftime('%Y-%m-%d')}")
    lines.append("")
    lines.append(f"_Generated: {pd.Timestamp.now().isoformat()}_")
    lines.append("")
    lines.append("## Active Rule")
    lines.append("")
    lines.append(f"- **Consolidation**: prior {rule['cons_d']} trading days all closed below $1.00")
    lines.append(f"- **Entry range**: today close in **[${rule['entry_lo']:.2f}, ${rule['entry_hi']:.2f})**")
    lines.append(f"- **Take profit**: entry × {rule['tp_ratio']:.2f} (= **+{(target_ratio-1)*100:.0f}%**)")
    lines.append(f"- **Max hold**: {hold_d} trading days")
    lines.append(f"- **Stop loss**: none (per backtest finding)")
    lines.append(f"- **Slippage assumption**: 2% round-trip")
    lines.append("")
    lines.append(f"_Rule trained on `{rule.get('trained_on_period', '?')}` "
                 f"(N={rule.get('train_n', '?')}, win {rule.get('train_win_rate', 0):.1%}, "
                 f"mean {rule.get('train_mean_return', 0):+.2%}). "
                 f"Valid until {rule.get('valid_until', '?')}._")
    lines.append("")

    if not signals:
        lines.append("## Signals Today")
        lines.append("")
        lines.append("**No new breakout signals.**")
        lines.append("")
    else:
        lines.append(f"## Signals Today — {len(signals)} New")
        lines.append("")
        lines.append("| Symbol | Today Close | Prev Close | Cons Avg | TP Target | Action |")
        lines.append("|---|---|---|---|---|---|")
        for s in signals:
            tp_target = s["today_close"] * target_ratio
            lines.append(f"| **{s['symbol']}** | ${s['today_close']:.2f} | ${s['prev_close']:.2f} | "
                         f"${s['consolidation_avg']:.2f} | ${tp_target:.2f} | "
                         f"BUY next-day open, TP ${tp_target:.2f}, max hold {hold_d}d |")
        lines.append("")
        lines.append("### Trade Plan")
        lines.append("")
        lines.append(f"For each signal, on the next trading day:")
        lines.append(f"1. Place market BUY at the OPEN")
        lines.append(f"2. Immediately place a limit SELL at the TP target above")
        lines.append(f"3. If TP not hit within {hold_d} trading days, force-sell at close on day {hold_d}")
        lines.append(f"4. Recommended position size: 25% of cash per signal (max 4 simultaneous)")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("_This report is generated by the rolling 3-month adaptive walk-forward system. "
                 "Past performance does not guarantee future results. "
                 "Paper trade for 6+ months before deploying real capital._")

    out_path.write_text("\n".join(lines), encoding="utf-8")


def update_index():
    """Generate/update reports/_index.md with links to all reports."""
    reports = sorted(REPORTS.glob("*.md"))
    reports = [r for r in reports if r.name != "_index.md"]
    lines = ["# All Daily Reports", "", f"Total: {len(reports)} reports", ""]
    # group by month
    by_month = {}
    for r in reports:
        month = r.stem[:7]
        by_month.setdefault(month, []).append(r)
    for month in sorted(by_month.keys(), reverse=True):
        lines.append(f"## {month}")
        lines.append("")
        for r in sorted(by_month[month], reverse=True):
            lines.append(f"- [{r.stem}](./{r.name})")
        lines.append("")
    (REPORTS / "_index.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--as-of", type=str, default=None,
                        help="Override scan date (YYYY-MM-DD). Default: today.")
    parser.add_argument("--rule-file", type=str, default=str(CONFIG),
                        help="Path to rule JSON")
    args = parser.parse_args()

    rule_path = Path(args.rule_file)
    if not rule_path.exists():
        print(f"ERROR: rule file {rule_path} missing. Run quarterly_retrain.py first.")
        return
    with open(rule_path) as f:
        rule = json.load(f)

    as_of = pd.Timestamp(args.as_of) if args.as_of else pd.Timestamp.now().normalize()

    print(f"Scan date: {as_of.date()}")
    print(f"Active rule: cons {rule['cons_d']}d / entry [${rule['entry_lo']:.2f}, ${rule['entry_hi']:.2f}) / "
          f"TP +{(rule['tp_ratio']-1)*100:.0f}% / hold {rule['hold_d']}d")

    signals = detect_signals(rule, as_of)
    print(f"\nDetected {len(signals)} signal(s)")

    out_path = REPORTS / f"{as_of.strftime('%Y-%m-%d')}.md"
    render_report(rule, as_of, signals, out_path)
    print(f"Wrote: {out_path}")

    update_index()
    print(f"Updated: {REPORTS / '_index.md'}")


if __name__ == "__main__":
    main()
