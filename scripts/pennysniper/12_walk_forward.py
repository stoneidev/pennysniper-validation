"""
Step 12: Walk-forward analysis — does the model improve as it learns?

Procedure:
  1. Sort events chronologically.
  2. For each step k = INITIAL_TRAIN, INITIAL_TRAIN+STEP, ...:
       - Train on events[0:k]
       - Predict events[k:k+STEP]  (truly OOS — never seen)
       - Record OOS metrics
  3. Plot OOS performance over time.

Interpretation:
  - If OOS metric IMPROVES with k → model is genuinely learning
  - If OOS metric is FLAT → model has hit data ceiling
  - If OOS metric DEGRADES → market changing faster than model adapts (drift)

Compare Logistic Regression and Random Forest. RF has high capacity (similar
to RL value function); if even RF cannot improve, more capacity (RL) won't help.
"""
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler

df = pd.read_csv("events_with_features.csv")
df = df.sort_values("date").reset_index(drop=True)

FEATURE_COLS = [
    "minutes_to_trigger",
    "pre_volume",
    "vol_last5",
    "vol_acceleration",
    "red_ratio",
    "max_pullback_pct",
    "return_std",
    "return_last5",
    "first_bar_close_vs_open",
    "price_above_vwap_pct",
    "bars_since_high",
    "rth_open_price",
    "pre_high_x_open",
]

# Drop any rows with NaN in features
df_clean = df.dropna(subset=FEATURE_COLS).reset_index(drop=True)
print(f"Events with full feature set: {len(df_clean)}")
print(f"Date range: {df_clean['date'].min()} → {df_clean['date'].max()}")
print(f"Baseline win rate: {df_clean['is_winner'].mean():.1%}")
print(f"Baseline mean return: {df_clean['minute_return'].mean():.2%}\n")

INITIAL_TRAIN = 30
STEP = 5  # predict 5 events at a time

results = []
for k in range(INITIAL_TRAIN, len(df_clean), STEP):
    end = min(k + STEP, len(df_clean))
    if end - k < 3:
        break

    train = df_clean.iloc[:k]
    test = df_clean.iloc[k:end]

    X_train = train[FEATURE_COLS].values
    y_train = train["is_winner"].values
    X_test = test[FEATURE_COLS].values
    y_test = test["is_winner"].values
    ret_test = test["minute_return"].values

    if y_train.sum() < 3 or (len(y_train) - y_train.sum()) < 3:
        continue

    scaler = StandardScaler().fit(X_train)
    Xs_train = scaler.transform(X_train)
    Xs_test = scaler.transform(X_test)

    # Logistic
    log_clf = LogisticRegression(class_weight="balanced", max_iter=1000)
    log_clf.fit(Xs_train, y_train)
    p_log_train = log_clf.predict_proba(Xs_train)[:, 1]
    p_log_test = log_clf.predict_proba(Xs_test)[:, 1]
    thr_log = np.median(p_log_train)
    take_log = p_log_test >= thr_log

    # RF — limit depth to prevent obvious overfit on small N
    rf_clf = RandomForestClassifier(
        n_estimators=200, max_depth=4, min_samples_leaf=3,
        class_weight="balanced", random_state=42, n_jobs=-1,
    )
    rf_clf.fit(X_train, y_train)
    p_rf_train = rf_clf.predict_proba(X_train)[:, 1]
    p_rf_test = rf_clf.predict_proba(X_test)[:, 1]
    thr_rf = np.median(p_rf_train)
    take_rf = p_rf_test >= thr_rf

    results.append({
        "train_size": k,
        "test_size": len(y_test),
        "test_baseline_winrate": float(y_test.mean()),
        "test_baseline_return": float(ret_test.mean()),
        "log_take_n": int(take_log.sum()),
        "log_winrate": float(y_test[take_log].mean()) if take_log.sum() else np.nan,
        "log_meanret": float(ret_test[take_log].mean()) if take_log.sum() else np.nan,
        "log_alpha": float(ret_test[take_log].mean() - ret_test.mean()) if take_log.sum() else np.nan,
        "rf_take_n": int(take_rf.sum()),
        "rf_winrate": float(y_test[take_rf].mean()) if take_rf.sum() else np.nan,
        "rf_meanret": float(ret_test[take_rf].mean()) if take_rf.sum() else np.nan,
        "rf_alpha": float(ret_test[take_rf].mean() - ret_test.mean()) if take_rf.sum() else np.nan,
    })

res = pd.DataFrame(results)
res.to_csv("walk_forward_results.csv", index=False)

print(f"\n{'train_n':>7} {'test_n':>6} {'base_wr':>7} {'log_wr':>7} {'log_α':>7} {'rf_wr':>7} {'rf_α':>7}")
for _, r in res.iterrows():
    print(
        f"{r['train_size']:>7.0f} "
        f"{r['test_size']:>6.0f} "
        f"{r['test_baseline_winrate']:>7.1%} "
        f"{r['log_winrate']:>7.1%} "
        f"{r['log_alpha']:>+7.2%} "
        f"{r['rf_winrate']:>7.1%} "
        f"{r['rf_alpha']:>+7.2%} "
    )

# Aggregate: cumulative OOS returns
print("\n=== Aggregate OOS performance across walk-forward ===")
all_log_rets = []
all_rf_rets = []
all_baseline_rets = []
for _, r in res.iterrows():
    # We have to reconstruct individual returns. Re-run loop saving returns.
    pass

# Re-run to collect per-trade OOS returns
log_oos_rets = []
rf_oos_rets = []
base_oos_rets = []
oos_dates = []
for k in range(INITIAL_TRAIN, len(df_clean), STEP):
    end = min(k + STEP, len(df_clean))
    if end - k < 3:
        break
    train = df_clean.iloc[:k]
    test = df_clean.iloc[k:end]
    X_train = train[FEATURE_COLS].values
    y_train = train["is_winner"].values
    X_test = test[FEATURE_COLS].values
    ret_test = test["minute_return"].values

    if y_train.sum() < 3 or (len(y_train) - y_train.sum()) < 3:
        continue
    scaler = StandardScaler().fit(X_train)
    Xs_train = scaler.transform(X_train)
    Xs_test = scaler.transform(X_test)

    log_clf = LogisticRegression(class_weight="balanced", max_iter=1000).fit(Xs_train, y_train)
    rf_clf = RandomForestClassifier(
        n_estimators=200, max_depth=4, min_samples_leaf=3,
        class_weight="balanced", random_state=42, n_jobs=-1,
    ).fit(X_train, y_train)

    p_log_train = log_clf.predict_proba(Xs_train)[:, 1]
    p_rf_train = rf_clf.predict_proba(X_train)[:, 1]
    p_log_test = log_clf.predict_proba(Xs_test)[:, 1]
    p_rf_test = rf_clf.predict_proba(X_test)[:, 1]
    thr_log = np.median(p_log_train)
    thr_rf = np.median(p_rf_train)

    for i, ret in enumerate(ret_test):
        base_oos_rets.append(ret)
        log_oos_rets.append(ret if p_log_test[i] >= thr_log else np.nan)
        rf_oos_rets.append(ret if p_rf_test[i] >= thr_rf else np.nan)
        oos_dates.append(test["date"].iloc[i])

oos = pd.DataFrame({
    "date": pd.to_datetime(oos_dates),
    "baseline": base_oos_rets,
    "logistic": log_oos_rets,
    "rf": rf_oos_rets,
})
oos = oos.sort_values("date").reset_index(drop=True)
oos.to_csv("walk_forward_oos.csv", index=False)

print(f"\nTotal OOS events: {len(oos)}")
print(f"\n{'strategy':<12} {'n_trades':>9} {'mean':>8} {'sum':>8} {'after 3%':>10}")
for col in ["baseline", "logistic", "rf"]:
    n = oos[col].notna().sum()
    m = oos[col].mean()
    s = oos[col].sum()
    after = oos[col].mean() - 0.03 if n else np.nan
    print(f"{col:<12} {n:>9} {m:>+7.2%} {s:>+7.2f} {after:>+9.2%}")

# Plot 1: rolling OOS alpha over time
fig, axes = plt.subplots(2, 1, figsize=(12, 9))

ax = axes[0]
ax.plot(res["train_size"], res["log_alpha"] * 100, "o-", label="Logistic alpha vs baseline", color="C0")
ax.plot(res["train_size"], res["rf_alpha"] * 100, "s-", label="Random Forest alpha vs baseline", color="C1")
ax.axhline(0, color="black", linewidth=0.5)
ax.axhline(3, color="red", linestyle="--", linewidth=0.7, label="+3% (cost-covering)")
ax.set_title(
    "Walk-forward OOS alpha (model return − baseline return) vs training size\n"
    "If model is genuinely learning, line should trend UP"
)
ax.set_xlabel("Training set size (events)")
ax.set_ylabel("OOS alpha vs baseline (%)")
ax.legend()
ax.grid(alpha=0.3)

# Plot 2: cumulative OOS returns
ax = axes[1]
oos_cum = oos.copy()
oos_cum["baseline_cum"] = oos_cum["baseline"].cumsum()
oos_cum["log_cum"] = oos_cum["logistic"].fillna(0).cumsum()
oos_cum["rf_cum"] = oos_cum["rf"].fillna(0).cumsum()
ax.plot(oos_cum["date"], oos_cum["baseline_cum"], label=f"baseline: {oos_cum['baseline_cum'].iloc[-1]:+.2f}", color="gray")
ax.plot(oos_cum["date"], oos_cum["log_cum"], label=f"logistic: {oos_cum['log_cum'].iloc[-1]:+.2f}", color="C0")
ax.plot(oos_cum["date"], oos_cum["rf_cum"], label=f"random forest: {oos_cum['rf_cum'].iloc[-1]:+.2f}", color="C1")
ax.axhline(0, color="black", linewidth=0.5)
ax.set_title("Cumulative OOS P&L (sum of per-trade returns, 0% cost)")
ax.set_xlabel("Date")
ax.set_ylabel("Cumulative return (sum)")
ax.legend()
ax.grid(alpha=0.3)

fig.tight_layout()
fig.savefig("walk_forward.png", dpi=120)
plt.close(fig)

print("\nSaved walk_forward.png")

# Trend check
print("\n=== Is the model improving over time? ===")
from scipy.stats import linregress
for col in ["log_alpha", "rf_alpha"]:
    sub = res[["train_size", col]].dropna()
    if len(sub) >= 3:
        s = linregress(sub["train_size"], sub[col])
        direction = "IMPROVING" if s.slope > 0 else "DEGRADING"
        sig = " (significant)" if s.pvalue < 0.05 else " (not significant)"
        print(f"  {col}: slope={s.slope*100:+.4f}%/event, p={s.pvalue:.3f} → {direction}{sig}")
