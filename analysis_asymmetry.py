"""
analysis_asymmetry.py
---------------------
Bilateral asymmetry analysis from summary_small.csv.

For each patient × exercise:
  - Identifies right and left limb sensors from the placement table
  - Computes Asymmetry Index (AI) = (Right - Left) / (Right + Left) × 100
      positive → right dominant, negative → left dominant
  - Tracks AI across exercise thirds (early / mid / late) to detect
    whether asymmetry increases, decreases, or stays stable

Output:
  asymmetry_results.csv   — one row per patient × exercise
"""

import numpy as np
import pandas as pd
from pathlib import Path

# ---------------------------------------------------------------------------
# Sensor placement: data/sensor_placement.json, read by sensor_placement.py.
# Keys = patient folder name, values = sensor ID per limb position
# ULR = Upper Limb Right, ULL = Upper Limb Left
# LLR = Lower Limb Right, LLL = Lower Limb Left
# ---------------------------------------------------------------------------
from sensor_placement import PLACEMENT

# Exercise → which limb pair(s) to compare. Ex_MS_Bracos/Ex_MI_Pernas only
# have sensor data for one limb pair; the swim exercises record all 4 limbs
# simultaneously, so each yields two rows (Leg pair + Arm pair).
EXERCISE_LIMBS = {
    "Ex_MS_Bracos": ["UL"],          # upper limbs
    "Ex_MI_Pernas": ["LL"],          # lower limbs
    "Ex_Swim_1":    ["LL", "UL"],
    "Ex_Swim_2":    ["LL", "UL"],
}

EXERCISE_LABELS = {
    "Ex_MS_Bracos": "Arm exercise",
    "Ex_MI_Pernas": "Leg exercise",
    "Ex_Swim_1":    "Swim 1",
    "Ex_Swim_2":    "Swim 2",
}


def _ai(right, left):
    """Asymmetry Index in %. Returns None if both are NaN/zero."""
    if right is None or left is None:
        return None
    r, l = float(right), float(left)
    if np.isnan(r) or np.isnan(l):
        return None
    total = r + l
    if total == 0:
        return None
    return (r - l) / total * 100.0


def _trend_label(ai_early, ai_late):
    """Classify whether asymmetry is increasing, decreasing, or stable."""
    if ai_early is None or ai_late is None:
        return "unknown"
    delta = abs(ai_late) - abs(ai_early)
    if delta > 3:
        return "increasing"
    elif delta < -3:
        return "decreasing"
    else:
        return "stable"


def build_asymmetry_table(summary_csv="summary_small.csv"):
    df = pd.read_csv(summary_csv)

    # Normalise sensor column: strip the trailing _0000000000
    df["sensor_id"] = df["sensor"].str.split("_").str[0]

    rows = []
    for patient, pgroup in df.groupby("patient"):
        placement = PLACEMENT.get(patient)
        if placement is None:
            continue  # no placement data for this patient

        for exercise, egroup in pgroup.groupby("exercise"):
            limb_types = EXERCISE_LIMBS.get(exercise, [])
            multi_limb = len(limb_types) > 1

            for limb_type in limb_types:
                if limb_type == "UL":
                    right_key, left_key = "ULR", "ULL"
                else:
                    right_key, left_key = "LLR", "LLL"

                right_id = placement.get(right_key)
                left_id  = placement.get(left_key)
                if right_id is None or left_id is None:
                    continue

                right_row = egroup[egroup["sensor_id"] == right_id]
                left_row  = egroup[egroup["sensor_id"] == left_id]

                if right_row.empty or left_row.empty:
                    continue

                r = right_row.iloc[0]
                l = left_row.iloc[0]

                load_r = r["mechanical_load_mean"]
                load_l = l["mechanical_load_mean"]

                early_r = r.get("load_early_mean")
                mid_r   = r.get("load_mid_mean")
                late_r  = r.get("load_late_mean")
                early_l = l.get("load_early_mean")
                mid_l   = l.get("load_mid_mean")
                late_l  = l.get("load_late_mean")

                ai_overall = _ai(load_r, load_l)
                ai_early   = _ai(early_r, early_l)
                ai_mid     = _ai(mid_r,   mid_l)
                ai_late    = _ai(late_r,  late_l)

                trend = _trend_label(ai_early, ai_late)

                if ai_overall is not None:
                    dominant = "Right" if ai_overall > 3 else ("Left" if ai_overall < -3 else "Symmetric")
                else:
                    dominant = "unknown"

                label = EXERCISE_LABELS.get(exercise, exercise)
                if multi_limb:
                    label += " — Leg" if limb_type == "LL" else " — Arm"

                rows.append({
                    "patient":          patient,
                    "exercise":         exercise,
                    "exercise_label":   label,
                    "limb_type":        limb_type,
                    "right_sensor":     right_id,
                    "left_sensor":      left_id,
                    "load_right":       round(load_r, 4) if not np.isnan(load_r) else None,
                    "load_left":        round(load_l, 4) if not np.isnan(load_l) else None,
                    "asymmetry_index":  round(ai_overall, 2) if ai_overall is not None else None,
                    "dominant_limb":    dominant,
                    "load_right_early": round(early_r, 4) if early_r and not np.isnan(early_r) else None,
                    "load_left_early":  round(early_l, 4) if early_l and not np.isnan(early_l) else None,
                    "ai_early":         round(ai_early, 2) if ai_early is not None else None,
                    "load_right_mid":   round(mid_r, 4) if mid_r and not np.isnan(mid_r) else None,
                    "load_left_mid":    round(mid_l, 4) if mid_l and not np.isnan(mid_l) else None,
                    "ai_mid":           round(ai_mid, 2) if ai_mid is not None else None,
                    "load_right_late":  round(late_r, 4) if late_r and not np.isnan(late_r) else None,
                    "load_left_late":   round(late_l, 4) if late_l and not np.isnan(late_l) else None,
                    "ai_late":          round(ai_late, 2) if ai_late is not None else None,
                    "ai_trend":         round(ai_late - ai_early, 2) if (ai_late is not None and ai_early is not None) else None,
                    "trend_pattern":    trend,
                })

    return pd.DataFrame(rows)


def print_summary(df):
    print("\n=== ASYMMETRY SUMMARY PER PATIENT ===")
    print(f"{'Patient':<28} {'Exercise':<14} {'AI%':>7} {'Dominant':<12} {'Trend':<14} {'Early->Late'}")
    print("-" * 95)
    for _, r in df.sort_values(["patient","exercise"]).iterrows():
        ai = f"{r['asymmetry_index']:+.1f}" if r['asymmetry_index'] is not None else "  N/A"
        trend_str = f"{r.get('ai_trend', None):+.1f}" if r.get('ai_trend') is not None else "N/A"
        early = f"{r['ai_early']:+.1f}" if r.get('ai_early') is not None else "?"
        late  = f"{r['ai_late']:+.1f}" if r.get('ai_late') is not None else "?"
        print(f"{r['patient']:<28} {r['exercise']:<14} {ai:>7}%  {r['dominant_limb']:<12} "
              f"{r['trend_pattern']:<14} {early} -> {late}")


if __name__ == "__main__":
    print("Building asymmetry table...")
    df = build_asymmetry_table("summary_small.csv")
    df.to_csv("asymmetry_results.csv", index=False, encoding="utf-8-sig")
    print(f"  asymmetry_results.csv: {len(df)} rows ({df['patient'].nunique()} patients)")

    print_summary(df)

    # Quick group stats
    print("\n=== GROUP LEVEL ===")
    for ex, limbs in EXERCISE_LIMBS.items():
        for limb in limbs:
            sub_df = df[(df["exercise"] == ex) & (df["limb_type"] == limb)]
            sub = sub_df["asymmetry_index"].dropna()
            if len(sub) == 0:
                continue
            tag = ex if len(limbs) == 1 else f"{ex} ({limb})"
            print(f"{tag}: n={len(sub)}  mean AI={sub.mean():+.1f}%  std={sub.std():.1f}%  "
                  f"right_dom={( sub > 3).sum()}  left_dom={(sub < -3).sum()}  sym={(sub.abs()<=3).sum()}")

    print("\nDone.")
