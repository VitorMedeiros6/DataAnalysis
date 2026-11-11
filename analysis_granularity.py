"""
Sensitivity-to-granularity check for Chapter 6.

Rebuilds the six exercise/limb panels used throughout Chapter 6 (Table
tab:absolute_intensity etc.), but for SPARC and mechanical load computed at
*whole-exercise* granularity (summary_small.csv, 250ms-window means
aggregated over the whole exercise) instead of the per-cycle granularity
(cycles_medium.csv / cycles_by_limb.csv) used elsewhere in the thesis.

Mirrors the exact patient/sensor/limb lookup logic of build_isolated_summary.py
so the two granularities are directly comparable panel-for-panel.
"""
import json
import pandas as pd
from scipy import stats

from sensor_placement import PLACEMENT
from build_isolated_summary import EXERCISE_LIMB_GROUPS

with open("participants.json", encoding="utf-8") as f:
    ANON = {pid: pid for pid in json.load(f)}

# Control 2 is a byte-for-byte duplicate of Control 1
# under a second name in tempos_protocolo.json; excluded here for the same reason it is
# excluded from every other PD-vs-Control comparison in this thesis (pseudo-replication).
EXCLUDED_DUPLICATE = "Control 2"

df = pd.read_csv("summary_small.csv")
df.columns = [c.lstrip("﻿") for c in df.columns]
df["sensor_id"] = df["sensor"].astype(str).str.split("_").str[0]

rows = []
for patient, pgroup in df.groupby("patient"):
    if patient == EXCLUDED_DUPLICATE:
        continue
    placement = PLACEMENT.get(patient)
    if placement is None:
        continue
    anon = ANON.get(patient)
    if anon is None:
        continue
    group = "PD" if anon.startswith("Patient") else "Control"

    for exercise, limb_type, label in EXERCISE_LIMB_GROUPS:
        egroup = pgroup[pgroup["exercise"] == exercise]
        if egroup.empty:
            continue
        right_id = placement.get("ULR" if limb_type == "UL" else "LLR")
        left_id = placement.get("ULL" if limb_type == "UL" else "LLL")
        for side, sensor_id in [("Right", right_id), ("Left", left_id)]:
            if not sensor_id:
                continue
            srows = egroup[egroup["sensor_id"] == sensor_id]
            for _, r in srows.iterrows():
                rows.append({
                    "patient": anon,
                    "group": group,
                    "panel": label,
                    "exercise": exercise,
                    "limb_type": limb_type,
                    "side": side,
                    "sparc_mean": r["sparc_mean"],
                    "mechanical_load_mean": r["mechanical_load_mean"],
                })

long_df = pd.DataFrame(rows)

# Collapse Right/Left into one value per patient/panel (mean of both sides,
# matching how the per-cycle absolute-intensity table pools both sensors
# per panel before comparing groups).
panel_df = (long_df.groupby(["patient", "group", "panel"])[["sparc_mean", "mechanical_load_mean"]]
            .mean().reset_index())

PANEL_ORDER = [label for _, _, label in EXERCISE_LIMB_GROUPS]
PANEL_DISPLAY = {
    "Arm": "Arms (isolated)",
    "Leg": "Legs (isolated)",
    "Swim 1 - Leg": "Swim 1 (Legs)",
    "Swim 1 - Arm": "Swim 1 (Arms)",
    "Swim 2 - Leg": "Swim 2 (Legs)",
    "Swim 2 - Arm": "Swim 2 (Arms)",
}

results = []
for panel in PANEL_ORDER:
    sub = panel_df[panel_df["panel"] == panel]
    pd_vals = sub[sub["group"] == "PD"]
    c_vals = sub[sub["group"] == "Control"]
    for metric, mlabel in [("mechanical_load_mean", "Mechanical load"), ("sparc_mean", "SPARC")]:
        a = pd_vals[metric].dropna()
        b = c_vals[metric].dropna()
        t, p = stats.ttest_ind(a, b, equal_var=False)
        pooled_sd = ((a.std(ddof=1) ** 2 + b.std(ddof=1) ** 2) / 2) ** 0.5
        d = (a.mean() - b.mean()) / pooled_sd if pooled_sd > 0 else float("nan")
        results.append({
            "panel": PANEL_DISPLAY[panel],
            "metric": mlabel,
            "n_pd": len(a), "mean_pd": a.mean(),
            "n_c": len(b), "mean_c": b.mean(),
            "t": t, "p": p, "d": d,
        })

res_df = pd.DataFrame(results)
pd.set_option("display.width", 140)
print(res_df.to_string(index=False, float_format=lambda x: f"{x:.3f}"))
res_df.to_csv("granularity_whole_exercise_results.csv", index=False)
print("\nSaved: granularity_whole_exercise_results.csv")
print(f"\nTotal comparisons: {len(res_df)}")
print(f"Significant (p<0.05): {(res_df['p'] < 0.05).sum()}")
