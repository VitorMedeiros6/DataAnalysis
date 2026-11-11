"""
build_isolated_summary.py
--------------------------
Builds the "isolated per-stroke/kick" metrics deliverables requested:
  - average speed, average force (mechanical load), average SPARC per stroke/kick,
    isolated per limb (arm/leg) and per exercise context (arm ex, leg ex, swim 1, swim 2)

Inputs:
  cycles_medium.csv  — one row per cycle (from analysis_results.py), must include
                        avg_velocity (added by the Avg_Velocity change in
                        data_analysis_medium.py)

Outputs:
  cycles_by_limb.csv          — long format, one row per cycle, tagged with
                                 exercise_label / limb_type / side, for patients
                                 with known sensor placement.
  isolated_metrics_summary.xlsx — one row per patient, 12 exercise/limb/side
                                 columns (Arm Right/Left, Leg Right/Left,
                                 Swim1-Leg Right/Left, Swim1-Arm Right/Left,
                                 Swim2-Leg Right/Left, Swim2-Arm Right/Left),
                                 each with 3 sub-metrics (Speed avg m/s, Force
                                 avg, SPARC avg) — Right and Left kept separate
                                 (bilateral AI comparisons remain in
                                 analysis_asymmetry.py).
"""

import numpy as np
import pandas as pd

from sensor_placement import PLACEMENT

# (exercise, limb_type, column label) — used to build the per-cycle long table.
EXERCISE_LIMB_GROUPS = [
    ("Ex_MS_Bracos", "UL", "Arm"),
    ("Ex_MI_Pernas", "LL", "Leg"),
    ("Ex_Swim_1",    "LL", "Swim 1 - Leg"),
    ("Ex_Swim_1",    "UL", "Swim 1 - Arm"),
    ("Ex_Swim_2",    "LL", "Swim 2 - Leg"),
    ("Ex_Swim_2",    "UL", "Swim 2 - Arm"),
]

# (exercise, limb_type, side, column label) — same order as EXERCISE_LIMB_GROUPS,
# split into Right/Left columns — used for the summary table.
PANEL_COLUMNS = [
    (exercise, limb_type, side, f"{label} {side}")
    for exercise, limb_type, label in EXERCISE_LIMB_GROUPS
    for side in ("Right", "Left")
]

EXERCISE_LABEL = {
    "Ex_MS_Bracos": "Arm exercise",
    "Ex_MI_Pernas": "Leg exercise",
    "Ex_Swim_1":    "Swim 1",
    "Ex_Swim_2":    "Swim 2",
}


def build_cycles_by_limb(cycles_csv="cycles_medium.csv"):
    df = pd.read_csv(cycles_csv)
    df["sensor_id"] = df["sensor"].str.split("_").str[0]

    rows = []
    for patient, pgroup in df.groupby("patient"):
        placement = PLACEMENT.get(patient)
        if placement is None:
            continue  # no known L/R sensor mapping for this patient

        for exercise, limb_type, _label in EXERCISE_LIMB_GROUPS:
            egroup = pgroup[pgroup["exercise"] == exercise]
            if egroup.empty:
                continue

            right_id = placement.get("ULR" if limb_type == "UL" else "LLR")
            left_id  = placement.get("ULL" if limb_type == "UL" else "LLL")

            for side, sensor_id in [("Right", right_id), ("Left", left_id)]:
                if not sensor_id:
                    continue
                srows = egroup[egroup["sensor_id"] == sensor_id]
                for _, r in srows.iterrows():
                    rows.append({
                        "patient":        patient,
                        "exercise":       exercise,
                        "exercise_label": EXERCISE_LABEL.get(exercise, exercise),
                        "limb_type":      limb_type,   # UL = arm, LL = leg
                        "side":           side,        # Right / Left
                        "sensor":         r["sensor"],
                        "cycle_number":   r["cycle_number"],
                        "duration_s":     r["duration_s"],
                        "avg_velocity_ms": r.get("avg_velocity"),
                        "peak_velocity_ms": r.get("peak_velocity"),
                        "mechanical_load": r["mechanical_load"],
                        "sparc":          r["sparc"],
                    })

    return pd.DataFrame(rows)


def build_summary_table(df_cycles):
    patients = sorted(df_cycles["patient"].unique())
    records = []

    for patient in patients:
        pdata = df_cycles[df_cycles["patient"] == patient]
        row = {"Patient": patient}

        for exercise, limb_type, side, label in PANEL_COLUMNS:
            sub = pdata[(pdata["exercise"] == exercise) & (pdata["limb_type"] == limb_type)
                        & (pdata["side"] == side)]
            speed = sub["avg_velocity_ms"].dropna()
            force = sub["mechanical_load"].dropna()
            sparc = sub["sparc"].dropna()

            row[(label, "Speed avg (m/s)")] = round(speed.mean(), 4) if len(speed) else None
            row[(label, "Force avg")]       = round(force.mean(), 2) if len(force) else None
            row[(label, "SPARC avg")]       = round(sparc.mean(), 2) if len(sparc) else None
            row[(label, "n cycles")]        = int(len(sub))

        records.append(row)

    df_summary = pd.DataFrame(records).set_index("Patient")
    df_summary.columns = pd.MultiIndex.from_tuples(df_summary.columns)
    return df_summary


if __name__ == "__main__":
    print("Building per-cycle limb-tagged table...")
    df_cycles = build_cycles_by_limb("cycles_medium.csv")
    df_cycles.to_csv("cycles_by_limb.csv", index=False, encoding="utf-8-sig")
    print(f"  cycles_by_limb.csv: {len(df_cycles)} rows ({df_cycles['patient'].nunique()} patients)")

    print("\nBuilding patient x exercise/limb summary table...")
    df_summary = build_summary_table(df_cycles)
    df_summary.to_excel("isolated_metrics_summary.xlsx")
    print(f"  isolated_metrics_summary.xlsx: {len(df_summary)} patients x {len(PANEL_COLUMNS)} exercise/limb columns")

    print("\nDone.")
