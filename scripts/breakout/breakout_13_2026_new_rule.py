"""
Apply NEW optimal rule to 2026 signals.

NEW RULE A (highest safety score from win-rate optimization):
  - Cons: 30 days under $1
  - Entry range: today close in [$1.20, $1.50)
  - Entry: NEXT day open
  - TP: +20% from entry (=entry × 1.20)
  - SL: none
  - Hold: 90 days max → exit at close

Compare with NEW RULE B:
  - Cons: 60 days
  - Entry range: $1.10 ~ $1.30
  - TP: +30%
  - Hold: 180 days
  - SL: none
"""
import pandas as pd
import numpy as np
from pathlib import Path

STOOQ_DIR = Path("/Users/stoni/Downloads/data/daily/us/nasdaq stocks")
OUT_DIR = Path("/Users/stoni/Downloads/pennysniper_validation/results/csv")
START_DATE = pd.Timestamp("2024-06-01")
SLIP = 0.02
MIN_AVG_VOL = 10_000


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
    df = df[df["date"] >= START_DATE].dropna(subset=["Open", "High", "Low", "Close"])
    if len(df) < 65:
        return None
    return df.sort_values("date").reset_index(drop=True)


def find_and_simulate(rule):
    """rule = dict(cons, entry_lo, entry_hi, tp_ratio, hold)"""
    cons = rule["cons"]
    elo, ehi = rule["entry_lo"], rule["entry_hi"]
    tp_r = rule["tp_ratio"]
    hold = rule["hold"]

    csv_files = []
    for d in STOOQ_DIR.iterdir():
        if d.is_dir():
            csv_files.extend(d.glob("*.txt"))

    rows_2026 = []
    rows_all = []
    for f in csv_files:
        sym = f.stem.upper().replace(".US", "")
        if sym.endswith("W"):
            continue
        df = parse_csv(f)
        if df is None:
            continue
        c = df["Close"].values
        o = df["Open"].values
        h = df["High"].values
        l = df["Low"].values
        v = df["Volume"].values
        dates = df["date"].values

        if not ((c < 1.0).any() and (c >= elo).any()):
            continue

        for i in range(cons, len(c) - 1):
            prior = c[i - cons : i]
            if not (prior < 1.0).all() or not (prior > 0).all():
                continue
            if v[i - cons : i].mean() < MIN_AVG_VOL:
                continue
            if not (elo <= c[i] < ehi):
                continue
            if i > 0 and c[i - 1] >= elo:
                continue
            if i + 1 >= len(c):
                continue
            entry = o[i + 1]
            if entry <= 0:
                continue

            tp_price = entry * tp_r
            future_h = h[i + 1:]
            future_c = c[i + 1:]
            n = min(hold, len(future_h))

            ret = None
            days_to_tp = None
            for j in range(n):
                if future_h[j] >= tp_price:
                    ret = tp_r - 1.0 - SLIP
                    days_to_tp = j + 1
                    break
            if ret is None:
                if n > 0:
                    ret = float(future_c[n - 1]) / entry - 1.0 - SLIP
                else:
                    continue

            current_max = float(h[i + 1:].max()) if len(h[i + 1:]) > 0 else None
            current_close = float(c[-1])

            event = {
                "symbol": sym,
                "date": pd.Timestamp(dates[i]).strftime("%Y-%m-%d"),
                "next_open": float(entry),
                "tp_price": float(tp_price),
                "tp_hit": int(days_to_tp is not None),
                "days_to_tp": days_to_tp,
                "horizon_complete": int(len(future_h) >= hold),
                "ret_at_horizon_or_tp": ret,
                "current_max_high": current_max,
                "current_close": current_close,
                "current_ret": current_close / entry - 1.0,
            }
            rows_all.append(event)
            if pd.Timestamp(dates[i]).year == 2026:
                rows_2026.append(event)

    return pd.DataFrame(rows_all), pd.DataFrame(rows_2026)


# ============================================================
# Rule A
# ============================================================
RULE_A = {
    "name": "Rule A (highest safety)",
    "cons": 30, "entry_lo": 1.20, "entry_hi": 1.50,
    "tp_ratio": 1.20, "hold": 90,
}

# Rule B
RULE_B = {
    "name": "Rule B (higher return)",
    "cons": 60, "entry_lo": 1.10, "entry_hi": 1.30,
    "tp_ratio": 1.30, "hold": 180,
}


def report_rule(rule):
    print(f"\n{'=' * 100}")
    print(f"{rule['name']}")
    print(f"  Cons {rule['cons']}d / Entry [${rule['entry_lo']:.2f}, ${rule['entry_hi']:.2f}) / "
          f"TP +{(rule['tp_ratio']-1)*100:.0f}% / Hold {rule['hold']}d / SL none")
    print(f"{'=' * 100}")

    all_events, events_2026 = find_and_simulate(rule)

    print(f"\nTotal signals (2024.06 ~ 2026.06): {len(all_events)}")
    print(f"  2024 signals: {len(all_events[pd.to_datetime(all_events['date']).dt.year == 2024])}")
    print(f"  2025 signals: {len(all_events[pd.to_datetime(all_events['date']).dt.year == 2025])}")
    print(f"  2026 signals: {len(events_2026)}")

    # Overall stats (only horizon-complete or TP-hit)
    eligible = all_events[(all_events["horizon_complete"] == 1) | (all_events["tp_hit"] == 1)]
    if len(eligible) > 0:
        rets = eligible["ret_at_horizon_or_tp"].values
        print(f"\nOverall (horizon-complete or TP-hit): N={len(eligible)}")
        print(f"  win_rate: {(rets > 0).mean():.1%}")
        print(f"  mean:     {rets.mean():+.2%}")
        print(f"  median:   {np.median(rets):+.2%}")
        print(f"  p10:      {np.percentile(rets, 10):+.2%}")
        print(f"  p90:      {np.percentile(rets, 90):+.2%}")
        print(f"  TP hit rate: {eligible['tp_hit'].mean():.1%}")

    # 2026 only
    if len(events_2026) > 0:
        print(f"\n2026 signals ({len(events_2026)}):")
        eligible_2026 = events_2026[events_2026["tp_hit"] == 1]
        if len(eligible_2026) > 0:
            rets_2026 = eligible_2026["ret_at_horizon_or_tp"].values
            print(f"  TP-hit (closed): {len(eligible_2026)} → all +{(rule['tp_ratio']-1-SLIP)*100:.0f}%")
        print(f"  Still in flight: {(events_2026['horizon_complete'] == 0).sum()}")
        print(f"  Closed without TP: {((events_2026['horizon_complete'] == 1) & (events_2026['tp_hit'] == 0)).sum()}")

        print(f"\n  ALL 2026 events:")
        print(f"  {'symbol':<7} {'date':<11} {'entry':>7} {'TP$':>7} {'TP_hit':>7} {'days':>5} "
              f"{'cur_max':>9} {'cur_close':>10} {'cur_ret':>8}")
        for _, ev in events_2026.iterrows():
            tp_s = "✓" if ev["tp_hit"] == 1 else " "
            days = int(ev["days_to_tp"]) if ev["tp_hit"] == 1 else None
            days_s = f"{days}d" if days else "-"
            ret_pct = ev["current_ret"] * 100
            cur_max_s = ("$%.2f" % ev["current_max_high"]) if ev["current_max_high"] else "—"
            print(f"  {ev['symbol']:<7} {ev['date']:<11} ${ev['next_open']:>6.2f} "
                  f"${ev['tp_price']:>6.2f} {tp_s:>7} {days_s:>5} "
                  f"{cur_max_s:>9} ${ev['current_close']:>9.2f} {ret_pct:>+7.1f}%")

    return all_events, events_2026


a_all, a_2026 = report_rule(RULE_A)
b_all, b_2026 = report_rule(RULE_B)

# Save 2026 watchlists
a_2026.to_csv(OUT_DIR / "rule_A_2026_signals.csv", index=False)
b_2026.to_csv(OUT_DIR / "rule_B_2026_signals.csv", index=False)
print(f"\n✓ Saved to {OUT_DIR}/rule_A_2026_signals.csv, rule_B_2026_signals.csv")
