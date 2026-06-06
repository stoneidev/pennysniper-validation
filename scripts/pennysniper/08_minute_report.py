"""
Step 8: Analyze minute-resolved chasing strategy results.

Compare:
  - Daily-bar realistic estimate (previous: +0.38% gross)
  - Minute-bar actual outcome (now)

The minute-bar version resolves the path ambiguity. This is the most honest
estimate we can produce without paying for tick data.
"""
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

df = pd.read_csv("chasing_trades_minute.csv")
print(f"Total rows: {len(df)}")
print(f"\nStatus breakdown:")
print(df["status"].value_counts().to_string())

ok = df[df["status"] == "ok"].copy()
print(f"\n=== Minute-resolved trades: N={len(ok)} ===\n")

print("Exit reason:")
print(ok["exit_reason"].value_counts().to_string())
print()

print(f"{'cost':<10} {'win%':>7} {'avg':>8} {'median':>8} {'sum':>9} {'compounded':>14}")
for cost in [0.00, 0.02, 0.03, 0.05, 0.08]:
    net = ok["minute_return"] - cost
    win = (net > 0).mean()
    avg = net.mean()
    med = net.median()
    s = net.sum()
    comp = (1 + net).prod()
    print(f"{cost:>5.0%}      {win:>6.1%} {avg:>7.2%} {med:>7.2%} {s:>8.2f} {comp:>14.2e}")

# Compare to previous daily-based estimate
print("\n=== Daily vs Minute comparison (same events) ===")
print(f"  daily realistic gross mean:  {ok['previous_realistic_return'].mean():.2%}")
print(f"  minute resolved gross mean:  {ok['minute_return'].mean():.2%}")
print(f"  daily realistic win rate:    {(ok['previous_realistic_return']>0).mean():.1%}")
print(f"  minute resolved win rate:    {(ok['minute_return']>0).mean():.1%}")

# Bars held distribution
print("\n=== Hold time (minutes from entry to exit) ===")
print(f"  median: {ok['bars_held'].median():.0f} min")
print(f"  mean:   {ok['bars_held'].mean():.1f} min")
print(f"  p25:    {ok['bars_held'].quantile(0.25):.0f} min")
print(f"  p75:    {ok['bars_held'].quantile(0.75):.0f} min")

# Plot 1: histogram
fig, axes = plt.subplots(1, 2, figsize=(14, 5))
axes[0].hist(ok["minute_return"] * 100, bins=30, edgecolor="black", color="steelblue")
axes[0].axvline(ok["minute_return"].mean() * 100, color="red", linestyle="--",
                label=f"mean = {ok['minute_return'].mean():.2%}")
axes[0].axvline(0, color="black", linewidth=0.5)
axes[0].set_title(f"Chasing +100% — minute-resolved per-trade return (N={len(ok)})")
axes[0].set_xlabel("Return %")
axes[0].set_ylabel("Frequency")
axes[0].legend()
axes[0].grid(alpha=0.3)

# Daily estimate vs minute actual scatter
axes[1].scatter(
    ok["previous_realistic_return"] * 100,
    ok["minute_return"] * 100,
    alpha=0.6,
    s=40,
)
axes[1].plot([-10, 15], [-10, 15], color="red", linestyle="--", linewidth=0.7,
             label="y = x (perfect agreement)")
axes[1].axhline(0, color="black", linewidth=0.5)
axes[1].axvline(0, color="black", linewidth=0.5)
axes[1].set_xlabel("Previous daily-based estimate (%)")
axes[1].set_ylabel("Minute-resolved actual (%)")
axes[1].set_title("How wrong was the daily estimate?")
axes[1].legend()
axes[1].grid(alpha=0.3)

fig.tight_layout()
fig.savefig("minute_analysis.png", dpi=120)
plt.close(fig)

# Equity curve
fig, ax = plt.subplots(figsize=(11, 5))
sorted_ok = ok.sort_values("date").reset_index(drop=True)
sorted_ok["date_dt"] = pd.to_datetime(sorted_ok["date"])
for cost, label in [(0.0, "0% cost"), (0.02, "2% cost"), (0.03, "3% cost"), (0.05, "5% cost")]:
    net = sorted_ok["minute_return"] - cost
    cum = net.cumsum()
    ax.plot(sorted_ok["date_dt"], cum, label=f"{label}: final={cum.iloc[-1]:.2f}")
ax.axhline(0, color="black", linewidth=0.5)
ax.set_title(f"Chasing +100% — minute-resolved equity curve (N={len(ok)})\n"
             "Polygon 1-min bars, path-resolved (SL-first if both reachable in same bar)")
ax.set_xlabel("Event date")
ax.set_ylabel("Cumulative return (sum)")
ax.legend()
ax.grid(alpha=0.3)
fig.tight_layout()
fig.savefig("minute_equity.png", dpi=120)
plt.close(fig)

# Disagreement analysis
ok["agreed"] = (np.sign(ok["minute_return"]) == np.sign(ok["previous_realistic_return"])).astype(int)
print(f"\n=== Daily vs minute agreement ===")
print(f"  agreed sign:    {ok['agreed'].sum()}/{len(ok)} = {ok['agreed'].mean():.1%}")
print(f"  daily WRONG (said win, actually lost): "
      f"{((ok['previous_realistic_return']>0) & (ok['minute_return']<=0)).sum()}")
print(f"  daily WRONG (said loss, actually won): "
      f"{((ok['previous_realistic_return']<=0) & (ok['minute_return']>0)).sum()}")

# Save
ok.to_csv("chasing_trades_minute_clean.csv", index=False)
print("\nSaved minute_analysis.png, minute_equity.png, chasing_trades_minute_clean.csv")
