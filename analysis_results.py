"""
analysis_results.py
-------------------
Reads results from results_medium_window/ and results_small_window/ and
produces four CSV files:

  summary_medium.csv  — one row per patient/sensor/exercise (aggregate stats)
  cycles_medium.csv   — one row per individual cycle (raw durations + metrics)
  summary_small.csv   — one row per patient/sensor/exercise (window aggregates)
  windows_small.csv   — one row per individual window (raw metrics)
"""

import json
import numpy as np
import pandas as pd
from pathlib import Path
from scipy import stats as scipy_stats

MEDIUM_DIR = Path("./results_medium_window")
SMALL_DIR  = Path("./results_small_window")

# TSFEL features extracted for Parkinson's-relevant summary (small window)
TSFEL_SELECTED = {
    "Magnitude_Mean":               "signal_mean",
    "Magnitude_Standard deviation": "signal_std",
    "Magnitude_Root mean square":   "signal_rms",
    "Magnitude_Kurtosis":           "signal_kurtosis",
    "Magnitude_Skewness":           "signal_skewness",
    "Magnitude_Average power":      "avg_power",
    "Magnitude_Area under the curve": "area_under_curve",
    "Magnitude_Autocorrelation":    "autocorrelation",
    "Magnitude_Spectral entropy":   "spectral_entropy",
    "Magnitude_Fundamental frequency": "dominant_frequency",
    "Magnitude_Power bandwidth":    "power_bandwidth",
    "Magnitude_Maximum peaks":      "n_peaks",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe(lst):
    """Filter out None/NaN, return as numpy array."""
    return np.array([v for v in lst if v is not None and not (isinstance(v, float) and np.isnan(v))], dtype=float)


def _stats(arr):
    """Return mean and std of an array, or (None, None) if empty."""
    if len(arr) == 0:
        return None, None
    return float(np.mean(arr)), float(np.std(arr))


def _fatigue_slope(values):
    """Linear slope of values vs index. Positive = slowing down / increasing over time."""
    if len(values) < 3:
        return None
    x = np.arange(len(values), dtype=float)
    slope, *_ = scipy_stats.linregress(x, values)
    return float(slope)


def _progression(values):
    """Split into thirds and return (early_mean, mid_mean, late_mean)."""
    n = len(values)
    if n < 3:
        return None, None, None
    t = max(1, n // 3)
    early = float(np.mean(values[:t]))
    mid   = float(np.mean(values[t:2*t]))
    late  = float(np.mean(values[2*t:]))
    return early, mid, late


def _group_by_exercise(json_files, split_token):
    """Group a list of Path objects by exercise name, splitting on split_token."""
    groups = {}
    for f in sorted(json_files):
        parts = f.stem.split(split_token)
        if len(parts) == 2:
            ex = parts[0]
            groups.setdefault(ex, []).append(f)
    return groups


# ---------------------------------------------------------------------------
# Medium window
# ---------------------------------------------------------------------------

def analyze_medium():
    summary_rows = []
    cycle_rows   = []

    for patient_dir in sorted(MEDIUM_DIR.iterdir()):
        if not patient_dir.is_dir():
            continue
        patient = patient_dir.name

        for sensor_dir in sorted(patient_dir.iterdir()):
            if not sensor_dir.is_dir():
                continue
            sensor = sensor_dir.name

            groups = _group_by_exercise(sensor_dir.glob("*.json"), "_movement_")

            for ex_name, files in sorted(groups.items()):
                movements = [json.load(open(f, encoding="utf-8")) for f in sorted(files)]
                if not movements:
                    continue

                # --- per-cycle data ---
                durations = _safe([m["Metadata"]["Movement_Duration_s"]     for m in movements])
                sparcs    = _safe([m["Clinical_Metrics"].get("SPARC_Smoothness") for m in movements])
                loads     = _safe([m["Clinical_Metrics"].get("Mechanical_Load")  for m in movements])
                peaks     = _safe([m["Clinical_Metrics"].get("Peak_Acceleration") for m in movements])
                rms_vals  = _safe([m["Clinical_Metrics"].get("RMS_Acceleration")  for m in movements])
                avg_vels  = _safe([m["Clinical_Metrics"].get("Avg_Velocity")  for m in movements])
                peak_vels = _safe([m["Clinical_Metrics"].get("Peak_Velocity") for m in movements])

                # Individual cycle rows
                for i, m in enumerate(movements):
                    cycle_rows.append({
                        "patient":       patient,
                        "sensor":        sensor,
                        "exercise":      ex_name,
                        "cycle_number":  m["Metadata"]["Movement_Number"],
                        "duration_s":    m["Metadata"]["Movement_Duration_s"],
                        "mechanical_load":    m["Clinical_Metrics"].get("Mechanical_Load"),
                        "peak_accel":         m["Clinical_Metrics"].get("Peak_Acceleration"),
                        "rms_accel":          m["Clinical_Metrics"].get("RMS_Acceleration"),
                        "sparc":              m["Clinical_Metrics"].get("SPARC_Smoothness"),
                        "avg_velocity":       m["Clinical_Metrics"].get("Avg_Velocity"),
                        "peak_velocity":      m["Clinical_Metrics"].get("Peak_Velocity"),
                    })

                # --- aggregate summary ---
                n               = len(durations)
                dur_mean, dur_std = _stats(durations)
                dur_cv          = (dur_std / dur_mean * 100) if (dur_mean and dur_mean > 0) else None
                dur_early, dur_mid, dur_late = _progression(durations)

                load_mean, load_std   = _stats(loads)
                peak_mean, peak_std   = _stats(peaks)
                rms_mean, rms_std     = _stats(rms_vals)
                sparc_mean, sparc_std = _stats(sparcs)
                avg_vel_mean, avg_vel_std   = _stats(avg_vels)
                peak_vel_mean, peak_vel_std = _stats(peak_vels)
                vel_early, vel_mid, vel_late = _progression(avg_vels)

                summary_rows.append({
                    "patient":            patient,
                    "sensor":             sensor,
                    "exercise":           ex_name,
                    # professor metrics
                    "n_cycles":           n,
                    "duration_mean_s":    dur_mean,
                    "duration_std_s":     dur_std,
                    "duration_cv_pct":    dur_cv,       # rhythm regularity (lower = more regular)
                    # progression / fatigue
                    "duration_early_s":   dur_early,
                    "duration_mid_s":     dur_mid,
                    "duration_late_s":    dur_late,
                    "fatigue_slope":      _fatigue_slope(durations),  # >0 = slowing down
                    # force / intensity
                    "mechanical_load_mean":  load_mean,
                    "mechanical_load_std":   load_std,
                    "peak_accel_mean":       peak_mean,
                    "peak_accel_std":        peak_std,
                    "rms_accel_mean":        rms_mean,
                    "rms_accel_std":         rms_std,
                    # velocity (single-integrated + detrended dynamic acceleration, m/s)
                    "avg_velocity_mean":     avg_vel_mean,
                    "avg_velocity_std":      avg_vel_std,
                    "peak_velocity_mean":    peak_vel_mean,
                    "peak_velocity_std":     peak_vel_std,
                    "velocity_early_ms":     vel_early,
                    "velocity_mid_ms":       vel_mid,
                    "velocity_late_ms":      vel_late,
                    "velocity_fatigue_slope": _fatigue_slope(avg_vels),  # <0 = slowing down
                    # smoothness
                    "sparc_mean":         sparc_mean,
                    "sparc_std":          sparc_std,
                    "sparc_fatigue_slope": _fatigue_slope(sparcs),  # <0 = getting less smooth
                })

    df_summary = pd.DataFrame(summary_rows)
    df_cycles  = pd.DataFrame(cycle_rows)
    return df_summary, df_cycles


# ---------------------------------------------------------------------------
# Small window
# ---------------------------------------------------------------------------

def analyze_small():
    summary_rows = []
    window_rows  = []

    for patient_dir in sorted(SMALL_DIR.iterdir()):
        if not patient_dir.is_dir():
            continue
        patient = patient_dir.name

        for sensor_dir in sorted(patient_dir.iterdir()):
            if not sensor_dir.is_dir():
                continue
            sensor = sensor_dir.name

            groups = _group_by_exercise(sensor_dir.glob("*.json"), "_window_")

            for ex_name, files in sorted(groups.items()):
                windows = [json.load(open(f, encoding="utf-8")) for f in sorted(files)]
                if not windows:
                    continue

                loads  = _safe([w["Clinical_Metrics"].get("Mechanical_Load")  for w in windows])
                sparcs = _safe([w["Clinical_Metrics"].get("SPARC_Smoothness") for w in windows])

                # Selected TSFEL features
                tsfel_arrays = {col: [] for col in TSFEL_SELECTED.values()}
                for w in windows:
                    tf = w.get("TSFEL_Features", {})
                    if isinstance(tf, str):
                        continue
                    for tsfel_key, col in TSFEL_SELECTED.items():
                        v = tf.get(tsfel_key)
                        if v is not None:
                            tsfel_arrays[col].append(v)

                # Individual window rows
                for w in windows:
                    tf = w.get("TSFEL_Features", {})
                    if isinstance(tf, str):
                        tf = {}
                    row = {
                        "patient":       patient,
                        "sensor":        sensor,
                        "exercise":      ex_name,
                        "window_number": w["Metadata"]["Window_Number"],
                        "mechanical_load": w["Clinical_Metrics"].get("Mechanical_Load"),
                        "sparc":           w["Clinical_Metrics"].get("SPARC_Smoothness"),
                    }
                    for tsfel_key, col in TSFEL_SELECTED.items():
                        row[col] = tf.get(tsfel_key)
                    window_rows.append(row)

                # Aggregate summary
                load_mean, load_std   = _stats(loads)
                sparc_mean, sparc_std = _stats(sparcs)
                load_early, load_mid, load_late = _progression(loads)

                row = {
                    "patient":  patient,
                    "sensor":   sensor,
                    "exercise": ex_name,
                    "n_windows": len(windows),
                    # intensity
                    "mechanical_load_mean": load_mean,
                    "mechanical_load_std":  load_std,
                    # smoothness
                    "sparc_mean":  sparc_mean,
                    "sparc_std":   sparc_std,
                    # fatigue / progression
                    "load_early_mean": load_early,
                    "load_mid_mean":   load_mid,
                    "load_late_mean":  load_late,
                    "load_fatigue_slope": _fatigue_slope(loads),
                    "sparc_fatigue_slope": _fatigue_slope(sparcs),
                }
                # TSFEL aggregates
                for col, vals in tsfel_arrays.items():
                    arr = _safe(vals)
                    m, s = _stats(arr)
                    row[f"{col}_mean"] = m
                    row[f"{col}_std"]  = s

                summary_rows.append(row)

    df_summary = pd.DataFrame(summary_rows)
    df_windows = pd.DataFrame(window_rows)
    return df_summary, df_windows


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("Analyzing medium window results...")
    df_med_sum, df_med_cyc = analyze_medium()
    df_med_sum.to_csv("summary_medium.csv", index=False, encoding="utf-8-sig")
    df_med_cyc.to_csv("cycles_medium.csv",  index=False, encoding="utf-8-sig")
    print(f"  summary_medium.csv  : {len(df_med_sum)} rows  ({df_med_sum['patient'].nunique()} patients)")
    print(f"  cycles_medium.csv   : {len(df_med_cyc)} rows")

    print("\nAnalyzing small window results...")
    df_sm_sum, df_sm_win = analyze_small()
    df_sm_sum.to_csv("summary_small.csv",  index=False, encoding="utf-8-sig")
    df_sm_win.to_csv("windows_small.csv",  index=False, encoding="utf-8-sig")
    print(f"  summary_small.csv   : {len(df_sm_sum)} rows  ({df_sm_sum['patient'].nunique()} patients)")
    print(f"  windows_small.csv   : {len(df_sm_win)} rows")

    print("\nDone.")
