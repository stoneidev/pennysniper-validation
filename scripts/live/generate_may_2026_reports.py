"""
Generate daily breakout reports for every trading day in May 2026.

Uses rule trained on 2026.01-03 (= rule_2026_q2.json).
"""
import subprocess
import sys
from pathlib import Path
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
RULE = REPO / "config" / "rule_2026_q2.json"

start = pd.Timestamp("2026-05-01")
end = pd.Timestamp("2026-05-30")
dates = pd.date_range(start, end, freq="B")

print(f"Generating reports for {len(dates)} trading days in May 2026")
print(f"Using rule: {RULE.name}\n")

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
        print(f"→ (no detect line)")

print("\nDone.")
