"""
Step 11: Out-of-sample validation.

Two approaches, run both:

  (A) SIMPLE FILTER (recommended for small N):
      Use only the top feature(s) from in-sample analysis to filter trades.
      Train on first 70%, test threshold on last 30%.
      Decision rule: trade only when feature > train-set median.

  (B) LOGISTIC REGRESSION:
      Train logistic on top 3 features. Test predicted-probability threshold.
      Compare OOS win rate vs baseline.

The honest test: does the train-set "edge" survive in test set?
With N=100, even modest filters will look great in-sample by chance.
"""
import pandas as pd
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

df = pd.read_csv("events_with_features.csv")
df = df.sort_values("date").reset_index(drop=True)
print(f"Total events: {len(df)}")
print(f"Date range: {df['date'].min()} → {df['date'].max()}")
print(f"Baseline win rate: {df['is_winner'].mean():.1%}")
print(f"Baseline mean return: {df['minute_return'].mean():.3%}\n")

# Chronological split: 70% train / 30% test
split = int(len(df) * 0.7)
train = df.iloc[:split].reset_index(drop=True)
test = df.iloc[split:].reset_index(drop=True)
print(f"Train: {len(train)} ({train['date'].min()} → {train['date'].max()})")
print(f"Test:  {len(test)} ({test['date'].min()} → {test['date'].max()})")
print(f"  train baseline win rate: {train['is_winner'].mean():.1%}")
print(f"  test  baseline win rate: {test['is_winner'].mean():.1%}\n")

# ========================================================================
# (A) SIMPLE FILTER on top single feature
# ========================================================================
print("=" * 72)
print("(A) SIMPLE FILTER on first_bar_close_vs_open (top univariate feature)")
print("=" * 72)
feat = "first_bar_close_vs_open"

# Find threshold in train: top quintile (80th percentile)
threshold = train[feat].quantile(0.80)
print(f"Train 80th percentile of {feat}: {threshold:.4f}")

# Train performance under filter
train_filtered = train[train[feat] >= threshold]
print(f"\nTrain (in-sample) with filter:")
print(f"  trades taken:  {len(train_filtered)} / {len(train)} = {len(train_filtered)/len(train):.0%}")
print(f"  win rate:      {train_filtered['is_winner'].mean():.1%}")
print(f"  mean return:   {train_filtered['minute_return'].mean():.2%}")
print(f"  sum return:    {train_filtered['minute_return'].sum():.2f}")

# Test performance under SAME train threshold
test_filtered = test[test[feat] >= threshold]
print(f"\nTest (out-of-sample) with same threshold:")
print(f"  trades taken:  {len(test_filtered)} / {len(test)} = {len(test_filtered)/len(test):.0%}")
print(f"  win rate:      {test_filtered['is_winner'].mean():.1%}" if len(test_filtered) else "  (no trades)")
print(f"  mean return:   {test_filtered['minute_return'].mean():.2%}" if len(test_filtered) else "")
print(f"  sum return:    {test_filtered['minute_return'].sum():.2f}" if len(test_filtered) else "")

# After-cost
if len(test_filtered):
    print(f"\n  After 3% cost: mean = {test_filtered['minute_return'].mean() - 0.03:.2%}")
    print(f"  After 5% cost: mean = {test_filtered['minute_return'].mean() - 0.05:.2%}")

# ========================================================================
# (B) LOGISTIC REGRESSION on top 3 features
# ========================================================================
print("\n" + "=" * 72)
print("(B) LOGISTIC REGRESSION on top 3 features")
print("=" * 72)

top3 = ["first_bar_close_vs_open", "bars_since_high", "price_above_vwap_pct"]
print(f"Features: {top3}")

X_train = train[top3].copy()
y_train = train["is_winner"].copy()
X_test = test[top3].copy()
y_test = test["is_winner"].copy()

# Drop rows with NaN
mask_tr = X_train.notna().all(axis=1)
mask_te = X_test.notna().all(axis=1)
X_train = X_train[mask_tr]
y_train = y_train[mask_tr]
X_test = X_test[mask_te]
y_test = y_test[mask_te]
ret_train = train.loc[mask_tr, "minute_return"]
ret_test = test.loc[mask_te, "minute_return"]

scaler = StandardScaler().fit(X_train)
Xs_train = scaler.transform(X_train)
Xs_test = scaler.transform(X_test)

clf = LogisticRegression(class_weight="balanced", max_iter=1000)
clf.fit(Xs_train, y_train)

print(f"\nLogistic coefficients:")
for f, c in zip(top3, clf.coef_[0]):
    print(f"  {f}: {c:+.3f}")
print(f"  intercept: {clf.intercept_[0]:+.3f}")

# Predicted probabilities
p_train = clf.predict_proba(Xs_train)[:, 1]
p_test = clf.predict_proba(Xs_test)[:, 1]

# Use train median probability as threshold  → trade top-half predictions
thr_p = np.median(p_train)
print(f"\nTrain median probability: {thr_p:.3f}")

train_take = p_train >= thr_p
test_take = p_test >= thr_p

print(f"\nTrain (in-sample) — trades where predicted prob >= median:")
print(f"  trades taken:  {train_take.sum()} / {len(train_take)} = {train_take.mean():.0%}")
print(f"  win rate:      {y_train[train_take].mean():.1%}" if train_take.sum() else "")
print(f"  mean return:   {ret_train[train_take].mean():.2%}" if train_take.sum() else "")

print(f"\nTest (OUT-OF-SAMPLE) — same model, same threshold:")
if test_take.sum() == 0:
    print("  (no trades)")
else:
    print(f"  trades taken:  {test_take.sum()} / {len(test_take)} = {test_take.mean():.0%}")
    print(f"  win rate:      {y_test[test_take].mean():.1%}")
    print(f"  mean return:   {ret_test[test_take].mean():.2%}")
    print(f"  sum return:    {ret_test[test_take].sum():.2f}")
    for cost in [0.02, 0.03, 0.05]:
        print(f"  after {cost:.0%} cost: mean = {ret_test[test_take].mean() - cost:.2%}")

# Higher threshold: top 20%
print("\n--- Higher conviction: top 20% predicted probabilities ---")
thr_p2 = np.quantile(p_train, 0.80)
train_take2 = p_train >= thr_p2
test_take2 = p_test >= thr_p2
print(f"Train 80th percentile p: {thr_p2:.3f}")
print(f"Train: {train_take2.sum()} trades, win rate {y_train[train_take2].mean():.1%}, "
      f"mean ret {ret_train[train_take2].mean():.2%}" if train_take2.sum() else "no train trades")
if test_take2.sum() == 0:
    print(f"Test:  no trades selected")
else:
    print(f"Test:  {test_take2.sum()} trades, "
          f"win rate {y_test[test_take2].mean():.1%}, "
          f"mean ret {ret_test[test_take2].mean():.2%}")
    for cost in [0.02, 0.03, 0.05]:
        print(f"  after {cost:.0%} cost: mean = {ret_test[test_take2].mean() - cost:.2%}")

# ========================================================================
# Honest verdict
# ========================================================================
print("\n" + "=" * 72)
print("HONEST VERDICT")
print("=" * 72)
test_unfiltered_mean = test["minute_return"].mean()
print(f"Test set unfiltered mean return: {test_unfiltered_mean:.2%}")
if test_take.sum() and test_take.sum() < len(test_take):
    test_filtered_mean = ret_test[test_take].mean()
    delta = test_filtered_mean - test_unfiltered_mean
    print(f"Test set filtered mean return:   {test_filtered_mean:.2%}")
    print(f"Filter ALPHA over baseline:      {delta:+.2%}")
    if delta > 0.03:
        print(">> Filter survives OOS and beats 3% cost. Worth investigating further.")
    elif delta > 0:
        print(">> Filter shows positive but small OOS edge — likely insufficient after costs.")
    else:
        print(">> Filter does NOT survive OOS. The in-sample edge was overfitting / noise.")
