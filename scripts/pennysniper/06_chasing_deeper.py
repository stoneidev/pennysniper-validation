"""
Step 6: Deeper analysis of chasing +100% strategy.

The key question: when a penny stock spikes +100% intraday, does it:
  (a) keep going up smoothly past +120% (TP wins)
  (b) hit +100% then crash back down (SL wins)
  (c) hit +120% briefly then come back (path-dependent, ambiguous)

Daily OHLC alone can't fully resolve (c), but candle SHAPE gives strong hints:

  - Close near High → late-day strength → likely TP held
  - Close near Low (after high spike) → spike then crash → likely SL hit
  - Close near Open after a +100% high → spike-and-fade pattern → SL likely

We classify each event by candle shape and report outcomes per shape.
"""
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

df = pd.read_csv("chasing_trades.csv")
print(f"Total events: {len(df)}")
print()

# Candle shape metrics
df["range"] = df["high"] - df["low"]
df["close_position"] = (df["close"] - df["low"]) / df["range"]  # 0=closed at low, 1=closed at high
df["close_vs_entry"] = df["close"] / df["entry"] - 1.0  # entry = 2x open

# How far past entry did the day close?
# If close_x_open >= 2.2: closed at or above TP → TP almost certainly held
# If close_x_open between 2.0 and 2.2: closed above entry but below TP
#   → ambiguous; could have hit TP intraday and pulled back, or never hit
# If close_x_open between 1.95 and 2.0: closed slightly below entry
#   → likely SL not hit, but no profit
# If close_x_open < 1.90: closed below SL → SL almost certainly hit

# === Conservative classification ===
# This treats the close as the most reliable signal.
def classify(row):
    cxo = row["close_x_open"]
    hxo = row["high_x_open"]
    if cxo >= 2.20:
        # Closed at TP or higher → TP held
        return "tp_held", +0.10
    elif cxo >= 2.00 and hxo >= 2.20:
        # Hit TP intraday but pulled back below TP. Realistic: TP would have
        # fired (limit order at TP). Outcome = TP.
        return "tp_pulled_back", +0.10
    elif cxo >= 2.00:
        # Closed in green but never hit TP. Hold to close.
        return "close_green", cxo / 2.0 - 1.0
    elif cxo >= 1.90:
        # Closed slightly below entry, no SL hit. Held to close.
        return "close_red_no_sl", cxo / 2.0 - 1.0
    else:
        # Closed below SL → SL hit
        return "sl_hit", -0.05

df[["realistic_outcome", "realistic_return"]] = df.apply(
    lambda r: pd.Series(classify(r)), axis=1
)

print("=== Realistic classification (uses close as primary evidence) ===")
print(df["realistic_outcome"].value_counts().to_string())
print()

# Stats
print(f"{'cost':<10} {'win%':>7} {'avg':>8} {'median':>8} {'sum':>8} {'compounded':>14}")
for cost in [0.00, 0.02, 0.03, 0.05, 0.08]:
    net = df["realistic_return"] - cost
    win = (net > 0).mean()
    avg = net.mean()
    med = net.median()
    s = net.sum()
    comp = (1 + net).prod()
    print(f"{cost:>5.0%}      {win:>6.1%} {avg:>7.2%} {med:>7.2%} {s:>7.2f} {comp:>14.2e}")

print()
print("=== Candle shape analysis ===")
print(f"  events where close >= 2.0x open (closed in profit zone):  {(df['close_x_open']>=2.0).sum()}/{len(df)} = {(df['close_x_open']>=2.0).mean():.1%}")
print(f"  events where close >= 2.2x open (closed at TP or above):  {(df['close_x_open']>=2.2).sum()}/{len(df)} = {(df['close_x_open']>=2.2).mean():.1%}")
print(f"  events where close <  1.9x open (closed below SL line):   {(df['close_x_open']<1.9).sum()}/{len(df)} = {(df['close_x_open']<1.9).mean():.1%}")
print(f"  events where close <  open       (red day despite +100%): {(df['close_x_open']<1.0).sum()}/{len(df)} = {(df['close_x_open']<1.0).mean():.1%}")
print()
print(f"  median close_x_open: {df['close_x_open'].median():.2f}")
print(f"  median high_x_open:  {df['high_x_open'].median():.2f}")
print(f"  median low_x_open:   {df['low_x_open'].median():.2f}")
print(f"  median close_position (0=low, 1=high): {df['close_position'].median():.2f}")

# Per-event return histogram + scatter
fig, axes = plt.subplots(1, 2, figsize=(14, 5))

axes[0].hist(df["realistic_return"] * 100, bins=30, edgecolor="black")
axes[0].axvline(df["realistic_return"].mean() * 100, color="red", linestyle="--",
                label=f"mean = {df['realistic_return'].mean():.2%}")
axes[0].axvline(0, color="black", linewidth=0.5)
axes[0].set_title(f"Chasing +100% — realistic per-trade return (N={len(df)})")
axes[0].set_xlabel("Return %")
axes[0].set_ylabel("Frequency")
axes[0].legend()
axes[0].grid(alpha=0.3)

# Scatter: high_x_open vs close_x_open
axes[1].scatter(df["high_x_open"], df["close_x_open"], alpha=0.6, s=30)
axes[1].axhline(2.0, color="green", linestyle="--", linewidth=0.7, label="entry (2x)")
axes[1].axhline(2.2, color="blue", linestyle="--", linewidth=0.7, label="TP (2.2x)")
axes[1].axhline(1.9, color="red", linestyle="--", linewidth=0.7, label="SL (1.9x)")
axes[1].axvline(2.0, color="black", linewidth=0.5)
axes[1].set_xlabel("High / Open  (intraday peak multiple)")
axes[1].set_ylabel("Close / Open (closing multiple)")
axes[1].set_title("Each dot = one +100% event\n(closer to diagonal = held gains; far below = spike-and-fade)")
axes[1].legend()
axes[1].grid(alpha=0.3)

fig.tight_layout()
fig.savefig("chasing_analysis.png", dpi=120)
plt.close(fig)

# Equity curve
fig, ax = plt.subplots(figsize=(11, 5))
df_sorted = df.sort_values("date").reset_index(drop=True)
df_sorted["date_dt"] = pd.to_datetime(df_sorted["date"])
for cost, label in [(0.0, "0% cost"), (0.03, "3% cost"), (0.05, "5% cost")]:
    net = df_sorted["realistic_return"] - cost
    cum = net.cumsum()
    ax.plot(df_sorted["date_dt"], cum, label=f"{label}: final={cum.iloc[-1]:.2f}")
ax.axhline(0, color="black", linewidth=0.5)
ax.set_title(f"Chasing +100% — cumulative per-trade P&L (N={len(df)})\n"
             "Realistic classification using close-based evidence")
ax.set_xlabel("Event date")
ax.set_ylabel("Cumulative return (sum)")
ax.legend()
ax.grid(alpha=0.3)
fig.tight_layout()
fig.savefig("chasing_equity.png", dpi=120)
plt.close(fig)

# Save processed
df.to_csv("chasing_trades_classified.csv", index=False)
print("\nSaved chasing_analysis.png, chasing_equity.png")
