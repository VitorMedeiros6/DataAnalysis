"""
Development-time error of the cycle detection before and after the fixed-axis method
(Chapter 4, "Introducing the fixed-axis primary method itself").

Combines the isolated-exercise cases of the two comparison tables written by
test_odek_ozcan_approach.py (SAMPLE_PATIENTS) and test_odek_ozcan_5patients_all_ex.py
(NEW_PATIENTS), so run those two first (`make validation` does). For every case with an expected
count (10 repetitions in Ex_MS_Bracos and Ex_MI_Pernas), it compares:
  - the adaptive multi-axis method, the only method before the change (`ours_diff`), and
  - the fixed-axis method after Ödek & Özcan (2023) (`oo_diff`),
and prints the mean absolute error of each over all cases together.
"""
from pathlib import Path

import pandas as pd

TEST_DIR = Path(__file__).resolve().parent
SOURCES = ["odek_ozcan_comparison.csv", "odek_ozcan_5patients_all_ex.csv"]

parts = []
for name in SOURCES:
    path = TEST_DIR / name
    if not path.exists():
        print(f"{name} not found: run the script that writes it first (make validation).")
        continue
    df = pd.read_csv(path, encoding="utf-8-sig").dropna(subset=["ours_diff", "oo_diff"])
    print(f"{name}: {len(df)} cases with an expected count")
    parts.append(df[["patient", "exercise", "ours_diff", "oo_diff"]])

if parts:
    cases = pd.concat(parts, ignore_index=True)
    print(f"\nAll cases: {len(cases)}")
    print(f"Mean absolute error, adaptive multi-axis method: {cases['ours_diff'].abs().mean():.2f} cycles")
    print(f"Mean absolute error, fixed-axis method:          {cases['oo_diff'].abs().mean():.2f} cycles")
