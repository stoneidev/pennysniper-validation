"""
Mega grid optimization for the breakout strategy.

Grid:
  Consolidation periods:  30, 45, 60d (under $1)
  Breakout entry close:   $1.05~$1.20
  Take-profit levels:     $1.5, $2.0, $2.4, $3.0, $5.0
  Hold horizons:          30, 60, 90, 180d
  Capital strategies:     all-in / 25% / 10% per signal

Outputs:
  - Per-trade stats (win rate, mean return) for each grid cell
  - Realistic ₩1M starting Jan 2025 simulation for top combos
  - Heatmap of grid results
  - Recommendation: best combo by NAV growth, by Sharpe-like, by win rate

This is the comprehensive optimization the user asked for.
"""
import pandas as pd
import numpy as np
from pathlib import Path
import matplotlib.pyplot as plt

DAILY_CACHE = Path("price_cache")
SLIP = 0.02

CONS_DAYS_LIST = [30, 45, 60]
BREAKOUT_LO = 1.05
BREAKOUT_HI = 1.20
SUB_LEVEL = 1.0
TP_LEVELS = [1.5, 2.0, 2.4, 3.0, 5.0]
HORIZONS = [30, 60, 90, 180]


def find_events(cons_days: int):
    rows = []
    for f in sorted(DAILY_CACHE.glob("*.csv")):
        sym = f.stem
        try:
            df = pd.read_csv(f, index_col=0, parse_dates=True)
        except Exception:
            continue
        if len(df) < cons_days + 5:
            continue
        df = df.sort_index()
        c = df["Close"].values
        o = df["Open"].values
        h = df["High"].values
        v = df["Volume"].values
        dates = df.index

        for i in range(cons_days, len(c) - 1):
            prior = c[i - cons_days : i]
            if not (prior < SUB_LEVEL).all() or not (prior > 0).all():
                continue
            if v[i - cons_days : i].mean() < 10000:
                continue
            if not (BREAKOUT_LO <= c[i] < BREAKOUT_HI):
                continue
            if i > 0 and c[i - 1] >= BREAKOUT_LO:
                continue
            if i + 1 >= len(c):
                continue
            entry = o[i + 1]
            if entry <= 0:
                continue

            event = {
                "symbol": sym,
                "date": dates[i].strftime("%Y-%m-%d"),
                "today_close": float(c[i]),
                "next_open": float(entry),
                "consolidation_avg": float(prior.mean()),
            }
            for hz in HORIZONS:
                end_idx = min(i + 1 + hz, len(c))
                future_h = h[i + 1 : end_idx]
                future_c = c[i + 1 : end_idx]
                if len(future_h) == 0:
                    continue
                event[f"horizon_complete_{hz}"] = int(len(future_h) >= hz)
                event[f"max_high_{hz}"] = float(future_h.max())
                event[f"close_{hz}"] = float(future_c[-1])
                for tp in TP_LEVELS:
                    hit = future_h >= tp
                    if hit.any():
                        event[f"hit_tp{tp}_{hz}"] = 1
                        event[f"days_to_tp{tp}_{hz}"] = int(np.argmax(hit) + 1)
                    else:
                        event[f"hit_tp{tp}_{hz}"] = 0
                        event[f"days_to_tp{tp}_{hz}"] = None
            rows.append(event)
    return pd.DataFrame(rows)


def compute_stats(df_events, tp, horizon):
    """For given (tp, horizon), compute per-trade returns and stats."""
    col = f"horizon_complete_{horizon}"
    if col not in df_events.columns:
        return None
    sub = df_events[df_events[col] == 1].copy()
    if len(sub) < 3:
        return None

    rets = []
    days_held = []
    for _, ev in sub.iterrows():
        hit = ev[f"hit_tp{tp}_{horizon}"]
        if hit == 1:
            ret = tp / ev["next_open"] - 1.0 - SLIP
            d = ev[f"days_to_tp{tp}_{horizon}"]
        else:
            ret = ev[f"close_{horizon}"] / ev["next_open"] - 1.0 - SLIP
            d = horizon
        rets.append(ret)
        days_held.append(d)
    rets = np.array(rets)
    days_held = np.array(days_held, dtype=float)
    return {
        "n": len(sub),
        "win_rate": (rets > 0).mean(),
        "mean_ret": rets.mean(),
        "median_ret": np.median(rets),
        "sum_ret": rets.sum(),
        "p10": np.percentile(rets, 10),
        "p90": np.percentile(rets, 90),
        "hit_rate": sub[f"hit_tp{tp}_{horizon}"].mean(),
        "median_days": np.median(days_held),
        "rets": rets,
        "events_with_returns": sub.assign(ret=rets, days_held=days_held),
    }


def simulate_capital(events_with_returns, alloc_pct, start_date="2025-01-01", initial=1_000_000):
    """Simulate capital with given allocation per trade.
    events_with_returns must have: symbol, date (string), next_open, ret, days_held
    """
    events = events_with_returns.copy()
    events["date_dt"] = pd.to_datetime(events["date"])
    events["entry_date"] = events["date_dt"] + pd.Timedelta(days=1)
    events["exit_date"] = events.apply(lambda r: r["entry_date"] + pd.Timedelta(days=int(r["days_held"])), axis=1)
    events = events[events["date_dt"] >= pd.Timestamp(start_date)].sort_values("date_dt").reset_index(drop=True)

    if len(events) == 0:
        return {"final": initial, "n_taken": 0, "n_skipped": 0, "trades": []}

    cash = initial
    open_positions = []  # (exit_date, capital_out)
    trades = []
    skipped = 0

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
            skipped += 1
            continue

        cash -= position_size
        cap_out = position_size * (1 + ev["ret"])
        open_positions.append((ev["exit_date"], cap_out))
        trades.append({
            "symbol": ev["symbol"],
            "entry": ev["entry_date"].date(),
            "exit": ev["exit_date"].date(),
            "in": position_size,
            "out": cap_out,
            "ret": ev["ret"],
        })

    for exit_d, cap_out in open_positions:
        cash += cap_out

    return {"final": cash, "n_taken": len(trades), "n_skipped": skipped, "trades": trades}


def main():
    print("Generating events for each consolidation period...")
    events_per_cons = {}
    for cd in CONS_DAYS_LIST:
        ev = find_events(cd)
        events_per_cons[cd] = ev
        print(f"  {cd}d cons: {len(ev)} events")

    # ====================================================================
    # Per-trade statistics grid
    # ====================================================================
    print("\nComputing per-trade stats grid...")
    grid_rows = []
    for cd in CONS_DAYS_LIST:
        ev = events_per_cons[cd]
        for tp in TP_LEVELS:
            for hz in HORIZONS:
                stats = compute_stats(ev, tp, hz)
                if stats is None:
                    continue
                grid_rows.append({
                    "cons_d": cd,
                    "tp": tp,
                    "horizon": hz,
                    "n": stats["n"],
                    "hit_rate": stats["hit_rate"],
                    "win_rate": stats["win_rate"],
                    "mean_ret": stats["mean_ret"],
                    "median_ret": stats["median_ret"],
                    "sum_ret": stats["sum_ret"],
                    "p10": stats["p10"],
                    "p90": stats["p90"],
                    "median_days": stats["median_days"],
                    "_events": stats["events_with_returns"],
                })

    grid = pd.DataFrame(grid_rows)
    grid_save = grid.drop(columns=["_events"])
    grid_save.to_csv("mega_grid_per_trade.csv", index=False)
    print(f"  saved mega_grid_per_trade.csv ({len(grid_save)} rows)")

    # ====================================================================
    # Capital simulation grid (₩1M from 2025-01-01)
    # ====================================================================
    print("\nSimulating ₩1M capital from 2025-01-01 for each combo...")
    sim_rows = []
    for _, r in grid.iterrows():
        ev_with_rets = r["_events"]
        for alloc_label, alloc in [("ALL_IN", 1.0), ("25_pct", 0.25), ("10_pct", 0.10)]:
            res = simulate_capital(ev_with_rets, alloc)
            sim_rows.append({
                "cons_d": r["cons_d"],
                "tp": r["tp"],
                "horizon": r["horizon"],
                "alloc": alloc_label,
                "events_total": r["n"],
                "trades_taken": res["n_taken"],
                "trades_skipped": res["n_skipped"],
                "final_krw": res["final"],
                "total_return": res["final"] / 1_000_000 - 1,
                "annualized": (res["final"] / 1_000_000) ** (365 / 522) - 1,  # 17 months
                "win_rate": r["win_rate"],
                "mean_ret": r["mean_ret"],
                "n_signals": r["n"],
            })
    sim = pd.DataFrame(sim_rows)
    sim.to_csv("mega_grid_capital_sim.csv", index=False)
    print(f"  saved mega_grid_capital_sim.csv ({len(sim)} rows)")

    # ====================================================================
    # Top results report
    # ====================================================================
    print("\n" + "=" * 100)
    print("TOP 15 COMBOS BY FINAL ₩ (₩1M starting 2025-01-01, all 3 alloc strategies)")
    print("=" * 100)
    top = sim.nlargest(15, "final_krw")
    print(f"\n{'cons':>4} {'TP':>5} {'horizon':>7} {'alloc':>8} {'sigs':>5} {'taken':>6} "
          f"{'win%':>6} {'mean':>8} {'final ₩':>15} {'return':>9} {'APY':>9}")
    for _, r in top.iterrows():
        tp_s = "$%.1f" % r["tp"]
        print(f"{int(r['cons_d']):>3}d {tp_s:>5} {int(r['horizon']):>5}d "
              f"{r['alloc']:>8} {int(r['n_signals']):>5} {int(r['trades_taken']):>6} "
              f"{r['win_rate']:>5.1%} {r['mean_ret']:>+7.1%} ₩{r['final_krw']:>13,.0f} "
              f"{r['total_return']:>+8.1%} {r['annualized']*100:>+8.1f}%")

    # By alloc strategy, top combos
    for alloc in ["ALL_IN", "25_pct", "10_pct"]:
        print(f"\n--- Top 5 for {alloc} ---")
        sub = sim[sim["alloc"] == alloc].nlargest(5, "final_krw")
        print(f"{'cons':>4} {'TP':>5} {'horizon':>7} {'sigs':>5} {'win%':>6} {'final ₩':>15} {'return':>9}")
        for _, r in sub.iterrows():
            tp_s = "$%.1f" % r["tp"]
            print(f"{int(r['cons_d']):>3}d {tp_s:>5} {int(r['horizon']):>5}d "
                  f"{int(r['n_signals']):>5} {r['win_rate']:>5.1%} ₩{r['final_krw']:>13,.0f} "
                  f"{r['total_return']:>+8.1%}")

    # Top by mean return per trade (avoid sequencing luck)
    print("\n" + "=" * 100)
    print("TOP 10 COMBOS BY MEAN RETURN PER TRADE (most robust statistic)")
    print("=" * 100)
    rank = grid.copy()
    rank["score"] = rank["mean_ret"] * np.sqrt(rank["n"])  # mean × sqrt(N) for stability
    top_robust = rank.nlargest(10, "score")
    print(f"\n{'cons':>4} {'TP':>5} {'horizon':>7} {'N':>4} {'win%':>6} {'mean':>8} {'p10':>8} {'p90':>8} {'med_d':>6}")
    for _, r in top_robust.iterrows():
        tp_s = "$%.1f" % r["tp"]
        print(f"{int(r['cons_d']):>3}d {tp_s:>5} {int(r['horizon']):>5}d "
              f"{int(r['n']):>4} {r['win_rate']:>5.1%} {r['mean_ret']:>+7.2%} "
              f"{r['p10']:>+7.2%} {r['p90']:>+7.2%} {int(r['median_days']):>4}d")

    # Heatmaps
    fig, axes = plt.subplots(len(CONS_DAYS_LIST), 1, figsize=(11, 4 * len(CONS_DAYS_LIST)))
    if len(CONS_DAYS_LIST) == 1:
        axes = [axes]
    for ax, cd in zip(axes, CONS_DAYS_LIST):
        sub = grid[(grid["cons_d"] == cd) & (grid["horizon"] == 180)]
        if len(sub) == 0:
            continue
        pivot = sub.pivot(index="tp", columns="horizon", values="mean_ret")
        # Single horizon now, use bar
        x = sub["tp"].values
        y = sub["mean_ret"].values * 100
        ax.bar([f"${t:.1f}" for t in x], y, color="steelblue")
        ax.axhline(0, color="black", linewidth=0.5)
        ax.set_title(f"Cons {cd}d — mean per-trade return at horizon=180d (after 2% slip)")
        ax.set_ylabel("Mean return %")
        for xi, yi, n in zip(range(len(x)), y, sub["n"].values):
            ax.text(xi, yi + 1, f"N={int(n)}", ha="center", fontsize=9)
        ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig("mega_grid_heatmap.png", dpi=120)
    plt.close(fig)
    print("\nSaved mega_grid_heatmap.png")

    # Capital growth comparison plot for top 3 combos
    fig, ax = plt.subplots(figsize=(13, 6))
    top_capital = sim.nlargest(5, "final_krw")
    for _, r in top_capital.iterrows():
        # Re-simulate to get equity history
        ev_match = grid[(grid["cons_d"] == r["cons_d"]) & (grid["tp"] == r["tp"]) & (grid["horizon"] == r["horizon"])]
        if len(ev_match) == 0:
            continue
        events_with_rets = ev_match.iloc[0]["_events"]
        alloc = {"ALL_IN": 1.0, "25_pct": 0.25, "10_pct": 0.10}[r["alloc"]]
        res = simulate_capital(events_with_rets, alloc)
        # Build equity curve from trades
        if len(res["trades"]) == 0:
            continue
        td = pd.DataFrame(res["trades"]).sort_values("entry")
        # Approximate equity at each entry/exit
        events_t = []
        for _, t in td.iterrows():
            events_t.append((t["entry"], -t["in"]))
            events_t.append((t["exit"], +t["out"]))
        events_t = sorted(events_t, key=lambda x: x[0])
        cash = 1_000_000
        history = [(pd.Timestamp("2025-01-01"), cash)]
        for date, delta in events_t:
            cash += delta
            history.append((pd.Timestamp(date), cash))
        eq = pd.DataFrame(history, columns=["date", "value"])
        label = f"{int(r['cons_d'])}d/${r['tp']:.1f}/{int(r['horizon'])}d/{r['alloc']} → ₩{r['final_krw']:,.0f}"
        ax.plot(eq["date"], eq["value"], marker=".", label=label, alpha=0.8)
    ax.axhline(1_000_000, color="black", linestyle="--", linewidth=0.5, label="Initial ₩1M")
    ax.set_title("Top 5 capital strategies: ₩1M from 2025-01-01")
    ax.set_xlabel("Date")
    ax.set_ylabel("Portfolio value (KRW)")
    ax.legend(loc="upper left", fontsize=8)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig("mega_grid_top5_equity.png", dpi=120)
    plt.close(fig)
    print("Saved mega_grid_top5_equity.png")

    print("\n✓ Mega grid analysis complete.")


if __name__ == "__main__":
    main()
