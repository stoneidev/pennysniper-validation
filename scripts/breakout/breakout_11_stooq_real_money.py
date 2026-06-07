"""
Re-run ₩1M capital sim on Stooq full universe.

Compare:
  - Prior (650 universe): ₩1M → ₩61M (best) on 30d/$3.0/90d ALL_IN
  - Stooq full (4,658 universe): true result
"""
import pandas as pd
import numpy as np
from pathlib import Path

OUT_DIR = Path("/Users/stoni/Downloads/pennysniper_validation/results/csv")
SLIP = 0.02


def simulate_capital(events, alloc_pct, tp, hz, start_date="2025-01-01"):
    """Simulate ₩1M with given allocation."""
    if len(events) == 0:
        return {"final": 1_000_000, "n_taken": 0, "trades": []}

    events = events.copy()
    events["date_dt"] = pd.to_datetime(events["date"])
    events = events[events["date_dt"] >= pd.Timestamp(start_date)].sort_values("date_dt").reset_index(drop=True)
    events["entry_date"] = events["date_dt"] + pd.Timedelta(days=1)

    cash = 1_000_000
    open_positions = []
    trades = []

    for _, ev in events.iterrows():
        bdate = ev["date_dt"]
        # Settle finished positions
        new_open = []
        for exit_d, cap_out in open_positions:
            if exit_d <= bdate:
                cash += cap_out
            else:
                new_open.append((exit_d, cap_out))
        open_positions = new_open

        position_size = cash * alloc_pct
        if position_size < 1000:
            continue

        # Compute return for this event
        hit = ev[f"hit_tp{tp}_{hz}"]
        if hit == 1:
            ret = tp / ev["next_open"] - 1.0 - SLIP
            days = ev[f"days_to_tp{tp}_{hz}"]
        else:
            ret = ev[f"close_{hz}"] / ev["next_open"] - 1.0 - SLIP
            days = hz
        if pd.isna(ret):
            continue

        cash -= position_size
        cap_out = position_size * (1 + ret)
        exit_date = ev["entry_date"] + pd.Timedelta(days=int(days))
        open_positions.append((exit_date, cap_out))
        trades.append({
            "symbol": ev["symbol"],
            "entry": ev["entry_date"].date(),
            "exit": exit_date.date(),
            "ret": ret,
        })

    for exit_d, cap_out in open_positions:
        cash += cap_out

    return {"final": cash, "n_taken": len(trades), "trades": trades}


def main():
    print("Re-simulating ₩1M from 2025-01-01 on Stooq full NASDAQ (4,658 stocks)\n")

    results = []
    for cd in [30, 45, 60]:
        csv_path = OUT_DIR / f"stooq_breakout_{cd}d.csv"
        if not csv_path.exists():
            continue
        events = pd.read_csv(csv_path)

        for tp in [1.5, 2.0, 2.4, 3.0, 5.0]:
            for hz in [30, 60, 90, 180]:
                col_complete = f"horizon_complete_{hz}"
                if col_complete not in events.columns:
                    continue
                ev_complete = events[events[col_complete] == 1]
                if len(ev_complete) < 5:
                    continue
                for alloc_label, alloc in [("ALL_IN", 1.0), ("25%", 0.25), ("10%", 0.10)]:
                    res = simulate_capital(ev_complete, alloc, tp, hz)
                    results.append({
                        "cons_d": cd, "tp": tp, "horizon": hz, "alloc": alloc_label,
                        "n_signals_in_period": len(ev_complete[pd.to_datetime(ev_complete["date"]) >= pd.Timestamp("2025-01-01")]),
                        "n_taken": res["n_taken"],
                        "final": res["final"],
                        "return_pct": res["final"] / 1_000_000 - 1,
                    })

    sim = pd.DataFrame(results)
    sim.to_csv(OUT_DIR / "stooq_capital_sim.csv", index=False)

    print("Top 15 by final value (Stooq full universe):\n")
    print(f"{'cons':>4} {'TP':>6} {'horizon':>8} {'alloc':>8} {'sigs':>5} {'taken':>6} {'final ₩':>15} {'return':>10}")
    top = sim.nlargest(15, "final")
    for _, r in top.iterrows():
        tp_s = "$%.1f" % r["tp"]
        print(f"{int(r['cons_d']):>3}d {tp_s:>5} {int(r['horizon']):>5}d {r['alloc']:>8} "
              f"{int(r['n_signals_in_period']):>5} {int(r['n_taken']):>6} "
              f"₩{r['final']:>13,.0f} {r['return_pct']:>+9.1%}")

    print("\n--- Top by alloc strategy ---")
    for alloc in ["ALL_IN", "25%", "10%"]:
        print(f"\n{alloc}:")
        sub = sim[sim["alloc"] == alloc].nlargest(5, "final")
        for _, r in sub.iterrows():
            tp_s = "$%.1f" % r["tp"]
            print(f"  {int(r['cons_d'])}d/{tp_s}/{int(r['horizon'])}d: "
                  f"₩{r['final']:,.0f} ({r['return_pct']:+.1%}, {int(r['n_taken'])} trades)")

    print("\n=== Comparison to prior 650-stock universe ===")
    print("Prior best (30d/$3.0/90d ALL_IN): ₩61,489,186 (+6,049%, 5 trades)")
    s = sim[(sim["cons_d"] == 30) & (sim["tp"] == 3.0) & (sim["horizon"] == 90) & (sim["alloc"] == "ALL_IN")]
    if len(s) > 0:
        r = s.iloc[0]
        print(f"Stooq full (30d/$3.0/90d ALL_IN):  ₩{r['final']:,.0f} ({r['return_pct']:+.1%}, {int(r['n_taken'])} trades)")


if __name__ == "__main__":
    main()
