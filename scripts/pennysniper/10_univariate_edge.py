"""
Step 10: Univariate edge analysis.

For each feature, check if it separates winners (TP) from losers (SL).
Methods:
  - t-test: mean difference statistically significant?
  - Quintile analysis: win rate in top vs bottom 20%
  - Mutual information: nonlinear relationship?

Honest interpretation:
  - p-value < 0.05 alone is NOT enough at N=100 with 19 features (multiple comparison)
  - Bonferroni-adjusted threshold: 0.05 / 19 ≈ 0.0026
  - We're looking for ROBUST signals, not p-hacking
"""
import pandas as pd
import numpy as np
from scipy import stats

df = pd.read_csv("events_with_features.csv")

FEATURE_COLS = [
    "minutes_to_trigger",
    "pre_volume",
    "pre_dollar_volume",
    "vol_last5",
    "dvol_last5",
    "vol_acceleration",
    "pre_bars_count",
    "red_ratio",
    "max_pullback_pct",
    "return_std",
    "return_last5",
    "return_earlier",
    "acceleration",
    "first_bar_close_vs_open",
    "price_above_vwap_pct",
    "bars_since_high",
    "rth_open_price",
    "pre_high_x_open",
]

baseline_winrate = df["is_winner"].mean()
n_features = len(FEATURE_COLS)
bonferroni = 0.05 / n_features
print(f"Baseline win rate: {baseline_winrate:.1%}")
print(f"N features tested: {n_features}")
print(f"Bonferroni-adjusted significance: p < {bonferroni:.4f}\n")

results = []
for col in FEATURE_COLS:
    sub = df[[col, "is_winner", "minute_return"]].dropna()
    if len(sub) < 10:
        continue
    winners = sub.loc[sub["is_winner"] == 1, col]
    losers = sub.loc[sub["is_winner"] == 0, col]
    if len(winners) < 3 or len(losers) < 3:
        continue

    # t-test (assumes roughly normal; we use Welch's, no equal var assumption)
    try:
        t_stat, p_val = stats.ttest_ind(winners, losers, equal_var=False)
    except Exception:
        t_stat, p_val = np.nan, np.nan

    # Quintile win rate
    q = sub[col].quantile([0.0, 0.2, 0.4, 0.6, 0.8, 1.0]).values
    # Make bins unique
    q = np.unique(q)
    if len(q) >= 3:
        sub_binned = sub.copy()
        sub_binned["bin"] = pd.cut(sub_binned[col], bins=q, include_lowest=True, duplicates="drop")
        bin_stats = sub_binned.groupby("bin", observed=True).agg(
            n=("is_winner", "size"),
            win_rate=("is_winner", "mean"),
            avg_ret=("minute_return", "mean"),
        )
        # Top vs bottom quintile
        top_winrate = bin_stats["win_rate"].iloc[-1] if len(bin_stats) else np.nan
        bot_winrate = bin_stats["win_rate"].iloc[0] if len(bin_stats) else np.nan
        spread = top_winrate - bot_winrate
    else:
        top_winrate = bot_winrate = spread = np.nan
        bin_stats = None

    results.append({
        "feature": col,
        "winners_mean": winners.mean(),
        "losers_mean": losers.mean(),
        "diff": winners.mean() - losers.mean(),
        "t_stat": t_stat,
        "p_value": p_val,
        "top_q_winrate": top_winrate,
        "bot_q_winrate": bot_winrate,
        "winrate_spread": spread,
        "bonferroni_pass": p_val < bonferroni if not np.isnan(p_val) else False,
        "raw_pass": p_val < 0.05 if not np.isnan(p_val) else False,
    })

res = pd.DataFrame(results).sort_values("p_value")
print("=== Feature edge ranking (sorted by p-value) ===\n")
print(f"{'feature':<26} {'win_mean':>10} {'lose_mean':>10} {'diff':>9} {'t':>6} {'p':>8} {'top_wr':>7} {'bot_wr':>7} {'spread':>7} {'sig':>6}")
for _, r in res.iterrows():
    sig = "**" if r["bonferroni_pass"] else ("*" if r["raw_pass"] else "")
    print(
        f"{r['feature']:<26} "
        f"{r['winners_mean']:>10.4g} "
        f"{r['losers_mean']:>10.4g} "
        f"{r['diff']:>+9.4g} "
        f"{r['t_stat']:>6.2f} "
        f"{r['p_value']:>8.4f} "
        f"{r['top_q_winrate']:>7.1%} "
        f"{r['bot_q_winrate']:>7.1%} "
        f"{r['winrate_spread']:>+7.1%} "
        f"{sig:>6}"
    )

print("\nLegend: * p<0.05 (raw),  ** p<bonferroni (genuinely significant after multiple-comparison correction)")
print()

# Show the BEST quintile in detail for top 3 features
print("\n=== Top 3 features: full quintile breakdown ===")
top_features = res.head(3)["feature"].tolist()
for col in top_features:
    print(f"\n--- {col} ---")
    sub = df[[col, "is_winner", "minute_return"]].dropna()
    sub["bin"] = pd.qcut(sub[col], q=5, duplicates="drop")
    bs = sub.groupby("bin", observed=True).agg(
        n=("is_winner", "size"),
        win_rate=("is_winner", "mean"),
        avg_ret=("minute_return", "mean"),
    )
    print(bs.to_string())

res.to_csv("univariate_results.csv", index=False)
print("\nSaved univariate_results.csv")
