"""
Compile the whole-exercise metrics into one table: full_exercise_features.csv

Reads every Results/<participant>/<sensor>/<exercise>_features.json written by
data_analysis.py and keeps its two Clinical_Metrics (Mechanical_Load and
SPARC_Smoothness), one row per participant x sensor x exercise.

Read by full_window_analysis.py and radar_values.py.
"""
import json
from pathlib import Path

import pandas as pd

COLUMNS = ["patient", "sensor", "exercise", "mechanical_load", "sparc"]


def build(results_dir="Results"):
    rows = []
    for path in sorted(Path(results_dir).glob("*/*/*_features.json")):
        with open(path, encoding="utf-8") as f:
            metrics = json.load(f)["Clinical_Metrics"]
        rows.append({
            "patient": path.parts[-3],
            "sensor": path.parts[-2],
            "exercise": path.name[: -len("_features.json")],
            "mechanical_load": metrics.get("Mechanical_Load"),
            "sparc": metrics.get("SPARC_Smoothness"),
        })
    return pd.DataFrame(rows, columns=COLUMNS)


if __name__ == "__main__":
    df = build()
    df.to_csv("full_exercise_features.csv", index=False)
    print(f"full_exercise_features.csv: {len(df)} rows ({df['patient'].nunique()} participants)")
