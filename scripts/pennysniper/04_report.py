"""
Step 4: Visualize and report.

Produces:
  - equity_curve.png (cumulative net P&L over time, 3 cost scenarios)
  - return_histogram.png (per-trade return distribution)
  - REPORT.md with honest summary
"""
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

TRADES_CSV = "trades.csv"
COSTS = {"optimistic (1%)": 0.01, "realistic (3%)": 0.03, "pessimistic (5%)": 0.05}


def main() -> None:
    df = pd.read_csv(TRADES_CSV, parse_dates=["entry_date", "exit_date"])
    df = df.sort_values("entry_date").reset_index(drop=True)

    # Equity curves (cumulative sum of per-trade returns, $1 notional/trade)
    fig, ax = plt.subplots(figsize=(11, 5))
    for label, c in COSTS.items():
        net = df["gross_return"] - c
        cum = net.cumsum()
        ax.plot(df["entry_date"], cum, label=f"{label}: final={cum.iloc[-1]:.2f}")
    ax.axhline(0, color="black", linewidth=0.5)
    ax.set_title("PennySniper proxy strategy — cumulative per-trade P&L (1 unit per trade)\n"
                 "Entry: next-day open after volume-surge + intraday +20% trigger | "
                 f"TP +10% / SL -5% / N={len(df)} trades")
    ax.set_xlabel("Entry date")
    ax.set_ylabel("Cumulative return (sum of per-trade %)")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig("equity_curve.png", dpi=120)
    plt.close(fig)

    # Histogram
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.hist(df["gross_return"] * 100, bins=40, edgecolor="black")
    ax.axvline(df["gross_return"].mean() * 100, color="red", linestyle="--",
               label=f"mean = {df['gross_return'].mean():.2%}")
    ax.axvline(df["gross_return"].median() * 100, color="orange", linestyle="--",
               label=f"median = {df['gross_return'].median():.2%}")
    ax.set_title(f"Per-trade gross return distribution (N={len(df)})")
    ax.set_xlabel("Gross return (%)")
    ax.set_ylabel("Frequency")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig("return_histogram.png", dpi=120)
    plt.close(fig)

    # Stats table
    rows = []
    for label, c in COSTS.items():
        net = df["gross_return"] - c
        wins = (net > 0).sum()
        win_rate = wins / len(net)
        avg = net.mean()
        std = net.std()
        sharpe_ann = (avg / std) * np.sqrt(252) if std > 0 else 0
        # Compounded equity assuming 100% allocation per trade (sequential)
        eq = (1 + net).cumprod().iloc[-1]
        rows.append({
            "scenario": label,
            "win_rate": win_rate,
            "mean_per_trade": avg,
            "median_per_trade": net.median(),
            "std": std,
            "sharpe_ann": sharpe_ann,
            "compounded_$1_to": eq,
        })
    stats = pd.DataFrame(rows)
    stats.to_csv("stats.csv", index=False)
    print(stats.to_string(index=False))

    # By exit reason
    er = df.groupby("exit_reason").agg(
        n=("gross_return", "size"),
        mean_ret=("gross_return", "mean"),
    ).sort_values("n", ascending=False)
    print("\nExit reason breakdown:")
    print(er.to_string())

    # Time period span
    print(f"\nDate range: {df['entry_date'].min().date()} → {df['exit_date'].max().date()}")
    print(f"Unique tickers: {df['symbol'].nunique()}")


if __name__ == "__main__":
    main()
