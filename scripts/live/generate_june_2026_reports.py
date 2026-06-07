"""
Generate daily breakout reports for trading days in June 2026 we have data for.

Uses current rule (config/current_rule.json), trained on 2026.03-05.
"""
import subprocess
import sys
from pathlib import Path
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
RULE = REPO / "config" / "current_rule.json"

# Stooq cache covers up to 2026-06-05. Generate for available dates.
start = pd.Timestamp("2026-06-01")
end = pd.Timestamp("2026-06-30")
dates = pd.date_range(start, end, freq="B")

print(f"Generating reports for {len(dates)} target trading days in June 2026")
print(f"Rule: {RULE}\n")

for d in dates:
    cmd = [
        sys.executable, str(REPO / "scripts" / "live" / "daily_report.py"),
        "--as-of", d.strftime("%Y-%m-%d"),
        "--rule-file", str(RULE),
    ]
    print(f"  {d.strftime('%Y-%m-%d')}", end=" ", flush=True)
    result = subprocess.run(cmd, capture_output=True, text=True)
    out = result.stdout
    n_line = [l for l in out.splitlines() if "Detected" in l]
    if n_line:
        print(f"→ {n_line[0].strip()}")
    else:
        print(f"→ (skipped or no data)")

print("\nDone.")
