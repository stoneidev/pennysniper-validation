"""
After RL walk-forward completes, generate comprehensive comparison.
Loads results from previous scripts and produces final comparison table.
"""
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path

CACHE = Path("xrp_cache")


def main():
    # Load logs
    files_needed = ["walkforward_log.csv", "rl_walkforward_log.csv"]
    for f in files_needed:
        if not (CACHE / f).exists():
            print(f"Missing: {f}. Run prerequisites first.")
            return

    grid_log = pd.read_csv(CACHE / "walkforward_log.csv")
    rl_log = pd.read_csv(CACHE / "rl_walkforward_log.csv")

    # Both should have same months. Merge for comparison.
    merged = grid_log.merge(rl_log, on="oos_month", suffixes=("_grid", "_rl"))
    merged["grid_sum"] = merged["oos_sum"]
    merged["rl_sum"] = merged["sum"]

    # Plot per-month comparison
    fig, ax = plt.subplots(figsize=(13, 6))
    x = np.arange(len(merged))
    w = 0.3
    ax.bar(x - w, merged["grid_sum"] * 100, w, label="Grid optimization", color="C0")
    ax.bar(x, merged["rl_sum"] * 100, w, label="Q-learning RL", color="C2")
    ax.set_xticks(x)
    ax.set_xticklabels(merged["oos_month"], rotation=45, ha="right")
    ax.axhline(0, color="black", linewidth=0.5)
    ax.set_title("Monthly OOS net P&L: grid optimization vs Q-learning RL")
    ax.set_ylabel("Net % per month")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig("xrp_grid_vs_rl.png", dpi=120)
    plt.close(fig)

    # Summary table
    print("Aggregate comparison (true walk-forward OOS):")
    print(f"\n  Grid: total {grid_log['oos_sum'].sum()*100:+.2f}%, "
          f"trades {grid_log['oos_n'].sum()}")
    print(f"  RL:   total {rl_log['sum'].sum()*100:+.2f}%, "
          f"trades {rl_log['n'].sum()}")


if __name__ == "__main__":
    main()
