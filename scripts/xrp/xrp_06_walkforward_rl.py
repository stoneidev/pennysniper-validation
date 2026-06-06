"""
Walk-forward Q-learning on XRP 1m data.

Each month:
  1. Train tabular Q-learning agent on ALL past 1-min data
  2. Apply learned policy to OOS month
  3. Move forward, retrain, repeat

State (discretized):
  s1: past 60-min return bucket  [<-7%, -7%~-5%, -5%~-3%, -3%~-1%, -1%~+1%, +1%~+3%, +3%~+5%, >+5%]  (8 buckets)
  s2: position flag  [0=flat, 1=long]
  s3: bars held (if long)  [0~60, 61~120, 121~240, 241~480, >480]  (5 buckets)

Action: 0=hold, 1=buy (if flat), 2=sell (if long)
Reward: net log return per bar (when in position) - cost on transitions

This is intentionally simple. RL CAN overfit even tabular Q-learning, especially
with sparse trades. We compare against fixed-rule baselines.
"""
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path
import json

CACHE = Path("xrp_cache")
FEE_RT = 0.002
SLIP = 0.0005
COST_PER_TRANSITION = (FEE_RT + SLIP) / 2.0  # half on entry, half on exit

LOOKBACK_MIN = 60
ACTIONS = ["hold", "buy", "sell"]


def load():
    df = pd.read_csv(CACHE / "spot_1m_2y.csv")
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, format="ISO8601")
    df = df.sort_values("timestamp").reset_index(drop=True)
    df["log_close"] = np.log(df["close"])
    df["ret_60m"] = df["close"].pct_change(LOOKBACK_MIN)
    return df


def discretize_ret(r):
    if pd.isna(r): return 4
    if r < -0.07: return 0
    if r < -0.05: return 1
    if r < -0.03: return 2
    if r < -0.01: return 3
    if r < 0.01: return 4
    if r < 0.03: return 5
    if r < 0.05: return 6
    return 7


def discretize_held(b):
    if b <= 60: return 0
    if b <= 120: return 1
    if b <= 240: return 2
    if b <= 480: return 3
    return 4


def state_key(ret_bucket, in_pos, held_bucket):
    if not in_pos:
        return (ret_bucket, 0, 0)  # held bucket irrelevant when flat
    return (ret_bucket, 1, held_bucket)


def train_q(df, end_idx, alpha=0.1, gamma=0.999, epsilon=0.1, n_passes=3, seed=42):
    """Train Q-table using on-policy SARSA-ish loop on bars [0, end_idx)."""
    rng = np.random.default_rng(seed)
    Q = {}
    closes = df["close"].values
    log_closes = df["log_close"].values
    rets = df["ret_60m"].values

    def get_q(s):
        if s not in Q:
            Q[s] = np.zeros(3)
        return Q[s]

    for _ in range(n_passes):
        in_pos = False
        held = 0
        entry_log = 0.0
        # Walk through bars in train range, agent makes decisions
        for i in range(LOOKBACK_MIN, end_idx - 1):
            rb = discretize_ret(rets[i])
            s = state_key(rb, in_pos, discretize_held(held))
            q = get_q(s)

            # epsilon-greedy
            if rng.random() < epsilon:
                a = rng.integers(0, 3)
            else:
                a = int(np.argmax(q))

            # Mask invalid actions (can't buy when long, can't sell when flat)
            if not in_pos and a == 2:
                a = 0
            if in_pos and a == 1:
                a = 0

            # Execute action, compute next state and reward
            reward = 0.0
            new_in_pos = in_pos
            new_held = held
            if not in_pos and a == 1:  # buy
                new_in_pos = True
                new_held = 1
                entry_log = log_closes[i]
                reward -= COST_PER_TRANSITION
            elif in_pos and a == 2:  # sell
                exit_log = log_closes[i]
                reward += (exit_log - entry_log)  # log return over holding
                reward -= COST_PER_TRANSITION
                new_in_pos = False
                new_held = 0
            elif in_pos:  # hold long
                new_held = held + 1

            # next state
            rb_next = discretize_ret(rets[i + 1])
            s_next = state_key(rb_next, new_in_pos, discretize_held(new_held))
            q_next = get_q(s_next)
            target = reward + gamma * np.max(q_next)
            q[a] = q[a] + alpha * (target - q[a])
            Q[s] = q

            in_pos = new_in_pos
            held = new_held

    return Q


def apply_policy(df, Q, start_idx, end_idx, max_hold=480):
    """Apply learned policy greedy on OOS slice."""
    closes = df["close"].values
    log_closes = df["log_close"].values
    rets = df["ret_60m"].values

    trades = []
    in_pos = False
    held = 0
    entry_idx = None
    entry_price = None
    for i in range(start_idx, end_idx):
        if i < LOOKBACK_MIN:
            continue
        rb = discretize_ret(rets[i])
        s = state_key(rb, in_pos, discretize_held(held))
        q = Q.get(s, np.zeros(3))
        a = int(np.argmax(q))

        # Mask invalid
        if not in_pos and a == 2:
            a = 0
        if in_pos and a == 1:
            a = 0

        # Force exit if held too long
        if in_pos and held >= max_hold:
            a = 2

        if not in_pos and a == 1:
            in_pos = True
            held = 1
            entry_idx = i
            entry_price = closes[i]
        elif in_pos and a == 2:
            exit_price = closes[i]
            gross = exit_price / entry_price - 1.0
            net = gross - FEE_RT - SLIP
            trades.append({
                "entry_time": df["timestamp"].iloc[entry_idx],
                "exit_time": df["timestamp"].iloc[i],
                "entry": float(entry_price),
                "exit": float(exit_price),
                "hold_min": held,
                "gross_ret": gross,
                "net_ret": net,
            })
            in_pos = False
            held = 0
            entry_idx = None
        elif in_pos:
            held += 1

    # If still in position at end of OOS slice, force exit
    if in_pos and entry_idx is not None:
        exit_price = closes[end_idx - 1]
        gross = exit_price / entry_price - 1.0
        net = gross - FEE_RT - SLIP
        trades.append({
            "entry_time": df["timestamp"].iloc[entry_idx],
            "exit_time": df["timestamp"].iloc[end_idx - 1],
            "entry": float(entry_price),
            "exit": float(exit_price),
            "hold_min": held,
            "gross_ret": gross,
            "net_ret": net,
            "forced_exit": True,
        })

    return pd.DataFrame(trades)


def main():
    print("Loading XRP 1-min data...")
    df = load()
    df["month"] = df["timestamp"].dt.tz_localize(None).dt.to_period("M")
    months = sorted(df["month"].unique())
    print(f"Months: {months[0]} ... {months[-1]}")

    INITIAL_TRAIN_MONTHS = 6
    print(f"Initial train: first {INITIAL_TRAIN_MONTHS} months")

    month_end_idx = {}
    for m in months:
        end_idx = df[df["month"] == m].index.max() + 1
        month_end_idx[m] = end_idx

    # ===================================================================
    # Walk-forward Q-learning
    # ===================================================================
    print(f"\n{'=' * 78}")
    print("Walk-forward Q-learning (monthly retrain)")
    print(f"{'=' * 78}")
    print(f"\n{'OOS_month':<12} {'Q_size':>7} {'OOS_n':>6} {'OOS_mean':>10} {'OOS_sum':>9}")

    rl_oos_trades = []
    monthly_log = []
    Q_history = {}

    for i in range(INITIAL_TRAIN_MONTHS, len(months)):
        oos_month = months[i]
        train_end_idx = month_end_idx[months[i - 1]]
        oos_start_idx = train_end_idx
        oos_end_idx = month_end_idx[oos_month]

        # Train
        Q = train_q(df, train_end_idx, n_passes=2, epsilon=0.1, seed=42 + i)
        Q_history[str(oos_month)] = len(Q)

        # Apply
        trades = apply_policy(df, Q, oos_start_idx, oos_end_idx)
        oos_n = len(trades)
        oos_mean = trades["net_ret"].mean() if oos_n > 0 else 0.0
        oos_sum = trades["net_ret"].sum() if oos_n > 0 else 0.0
        print(f"{str(oos_month):<12} {len(Q):>7} {oos_n:>6} {oos_mean:>+9.4%} {oos_sum:>+8.4f}")

        if oos_n > 0:
            rl_oos_trades.append(trades.assign(oos_month=str(oos_month)))
        monthly_log.append({
            "oos_month": str(oos_month),
            "q_size": len(Q),
            "n": oos_n,
            "mean": oos_mean,
            "sum": oos_sum,
        })

    pd.DataFrame(monthly_log).to_csv(CACHE / "rl_walkforward_log.csv", index=False)

    if rl_oos_trades:
        rl_all = pd.concat(rl_oos_trades, ignore_index=True)
    else:
        rl_all = pd.DataFrame()

    # ===================================================================
    # Compute baselines on same OOS period
    # ===================================================================
    first_oos_idx = month_end_idx[months[INITIAL_TRAIN_MONTHS - 1]]
    last_idx = month_end_idx[months[-1]]
    days = (df.iloc[last_idx - 1]["timestamp"] - df.iloc[first_oos_idx]["timestamp"]).total_seconds() / 86400

    # Helper for fixed-rule simulation
    def simulate_fixed(df, threshold, hold_min, start_idx, end_idx):
        closes = df["close"].values
        rets = df["ret_60m"].values
        last_signal = -10**9
        trades = []
        for i in range(max(start_idx, LOOKBACK_MIN), end_idx - hold_min):
            if rets[i] <= threshold and i - last_signal >= hold_min:
                entry = closes[i]
                exit_p = closes[i + hold_min]
                trades.append({
                    "entry_time": df["timestamp"].iloc[i],
                    "gross_ret": exit_p / entry - 1.0,
                    "net_ret": exit_p / entry - 1.0 - FEE_RT - SLIP,
                })
                last_signal = i
        return pd.DataFrame(trades)

    # Baseline: -7% fixed
    bl_minus7 = simulate_fixed(df, -0.07, 240, first_oos_idx, last_idx)
    # Baseline: -5% fixed
    bl_minus5 = simulate_fixed(df, -0.05, 240, first_oos_idx, last_idx)

    # ===================================================================
    # Aggregate comparison
    # ===================================================================
    print(f"\n{'=' * 78}")
    print(f"AGGREGATE OOS COMPARISON ({months[INITIAL_TRAIN_MONTHS]} → {months[-1]}, {days:.0f} days)")
    print(f"{'=' * 78}")
    print(f"\n{'strategy':<35} {'N':>5} {'win%':>7} {'mean_net':>10} {'total':>9} {'APY':>9}")
    for label, t in [
        ("Naive -7% / 240m fixed", bl_minus7),
        ("Naive -5% / 240m fixed", bl_minus5),
        ("Walk-forward Q-learning", rl_all),
    ]:
        if len(t) == 0:
            print(f"{label:<35} {0:>5}")
            continue
        wr = (t["net_ret"] > 0).mean()
        mean_ret = t["net_ret"].mean()
        total = t["net_ret"].sum()
        apy = total / days * 365 * 100
        print(f"{label:<35} {len(t):>5} {wr:>6.1%} {mean_ret:>+9.3%} {total:>+8.4f} {apy:>+8.2f}%")

    # ===================================================================
    # Plot equity curves
    # ===================================================================
    fig, axes = plt.subplots(2, 1, figsize=(13, 9))

    if len(rl_all) > 0:
        rl_sorted = rl_all.sort_values("entry_time").reset_index(drop=True)
        rl_sorted["cum_net"] = rl_sorted["net_ret"].cumsum()
        axes[0].plot(rl_sorted["entry_time"], rl_sorted["cum_net"] * 100,
                     marker="o", label=f"Q-learning (N={len(rl_all)})", color="C2")
    if len(bl_minus7) > 0:
        b7 = bl_minus7.sort_values("entry_time").reset_index(drop=True)
        b7["cum_net"] = b7["net_ret"].cumsum()
        axes[0].plot(b7["entry_time"], b7["cum_net"] * 100,
                     marker="^", label=f"Naive -7% (N={len(bl_minus7)})", color="C1")
    if len(bl_minus5) > 0:
        b5 = bl_minus5.sort_values("entry_time").reset_index(drop=True)
        b5["cum_net"] = b5["net_ret"].cumsum()
        axes[0].plot(b5["entry_time"], b5["cum_net"] * 100,
                     marker="s", label=f"Naive -5% (N={len(bl_minus5)})", color="C0", alpha=0.7)
    axes[0].axhline(0, color="black", linewidth=0.5)
    axes[0].set_title(f"OOS net P&L: Q-learning vs naive baselines (true walk-forward, {days:.0f} OOS days)")
    axes[0].set_ylabel("Cumulative net %")
    axes[0].legend()
    axes[0].grid(alpha=0.3)

    # Q-table size growth (proxy for "model complexity")
    log_df = pd.DataFrame(monthly_log)
    if len(log_df) > 0:
        axes[1].bar(range(len(log_df)), log_df["sum"] * 100,
                    color=["green" if v > 0 else "red" for v in log_df["sum"]])
        axes[1].set_xticks(range(len(log_df)))
        axes[1].set_xticklabels(log_df["oos_month"], rotation=45, ha="right")
        axes[1].axhline(0, color="black", linewidth=0.5)
        axes[1].set_title("Q-learning monthly OOS net P&L (% of capital per trade, summed within month)")
        axes[1].set_ylabel("Monthly net %")
        axes[1].grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig("xrp_rl_walkforward.png", dpi=120)
    plt.close(fig)
    print("\nSaved xrp_rl_walkforward.png")


if __name__ == "__main__":
    main()
