"""
Diagnostic (test/ only, READ-ONLY on production data): checks whether a
FIXED anatomical axis (not the current "most peaks wins" heuristic) gives
cycle counts closer to the expected 10, for Ex_MS_Bracos (arm swing,
parallel to the water line) and Ex_MI_Pernas (leg kick, perpendicular to
the water line).

For each correctly-matched sensor/exercise pair (via data/participants.json), reports
the RAW (non-abs) peak count on x, y, z individually, so we can see if one
axis consistently tracks closest to 10 across patients for each exercise.
"""
import json
import numpy as np
import pandas as pd
from pathlib import Path
import skdh

import sys
TEST_DIR = Path(__file__).resolve().parent
ROOT = TEST_DIR.parent
sys.path.insert(0, str(TEST_DIR))
sys.path.insert(0, str(ROOT))

from scipy.signal import find_peaks, butter, filtfilt
from participants import PLACEMENT_FILES

PROTOCOL = json.load(open(ROOT / "data" / "tempos_protocolo.json", encoding="utf-8"))
SENSOR_DATA = ROOT / "data" / "sensor_data"

SAMPLE_PATIENTS = [
    "Patient 1",
    "Patient 2",
    "Patient 4",
    "Patient 5",
    "Patient 12",
    "Patient 10",
    "Patient 7",
]

EXPECTED = 10
FILTER_PAD_S = 3.0


def parse_ts(t_str, ref_date):
    h, m, s = int(t_str.split('h')[0]), int(t_str.split('h')[1].split('m')[0]), int(t_str.split('m')[1].replace('s', ''))
    from datetime import datetime, timedelta, timezone
    return datetime.combine(ref_date, datetime.min.time()).replace(tzinfo=timezone.utc) + timedelta(hours=h, minutes=m, seconds=s)


def axis_peak_counts(df_full, h_start, h_end, fs, exercise_name):
    """Returns raw peak count per axis (x, y, z) using the SAME filter band as production."""
    ref_date = df_full['timestamp'].iloc[0].date()
    t0, t1 = parse_ts(h_start, ref_date), parse_ts(h_end, ref_date)

    core = df_full[(df_full['timestamp'] >= t0) & (df_full['timestamp'] <= t1)]
    if len(core) < 10:
        return None

    nyq = fs / 2
    if "Pernas" in exercise_name or "MI" in exercise_name:
        low_hz, high_hz, min_dist_s = 0.3, 3.0, 0.8
    else:
        low_hz, high_hz, min_dist_s = 0.3, 2.0, 0.9
    b, a = butter(4, [low_hz / nyq, min(high_hz / nyq, 0.99)], btype='band')

    pad = pd.Timedelta(seconds=FILTER_PAD_S)
    seg_pad = df_full[(df_full['timestamp'] >= t0 - pad) & (df_full['timestamp'] <= t1 + pad)]
    n_pre = int(((core['timestamp'].iloc[0] - seg_pad['timestamp'].iloc[0]).total_seconds()) * fs)
    n_core = len(core)

    counts = {}
    for col in ('x', 'y', 'z'):
        filt_pad = filtfilt(b, a, seg_pad[col].values)
        filt_core = filt_pad[n_pre: n_pre + n_core]
        prominence = filt_core.std() * 1.0
        peaks, _ = find_peaks(filt_core, distance=int(fs * min_dist_s), prominence=prominence)
        counts[col] = len(peaks)
    return counts


rows = []
for patient in SAMPLE_PATIENTS:
    placement = PLACEMENT_FILES.get(patient)
    proto = PROTOCOL.get(patient)
    if placement is None or proto is None:
        continue

    for ex_name in ("Ex_MS_Bracos", "Ex_MI_Pernas"):
        limb = "UL" if ex_name == "Ex_MS_Bracos" else "LL"
        for side, key in [("Right", "ULR" if limb == "UL" else "LLR"),
                           ("Left", "ULL" if limb == "UL" else "LLL")]:
            sensor_filename = placement.get(key)
            if not sensor_filename:
                continue
            cwa_path = SENSOR_DATA / patient / sensor_filename
            times_cfg = proto.get(sensor_filename, {}).get(ex_name)
            if not cwa_path.exists() or not times_cfg:
                continue
            h_start, h_end = times_cfg.get("start_time"), times_cfg.get("end_time")
            if not h_start or not h_end:
                continue

            try:
                reader = skdh.io.ReadCwa()
                data = reader.predict(file=str(cwa_path))
                accel, times, fs = data['accel'], data['time'], data['fs']
                df_full = pd.DataFrame({
                    'timestamp': pd.to_datetime(times, unit='s', utc=True),
                    'x': accel[:, 0], 'y': accel[:, 1], 'z': accel[:, 2],
                })
                counts = axis_peak_counts(df_full, h_start, h_end, fs, ex_name)
            except Exception as e:
                print(f"[ERROR] {patient}/{sensor_filename}/{ex_name}: {e}")
                continue
            if counts is None:
                continue

            best_axis = min(counts, key=lambda k: abs(counts[k] - EXPECTED))
            rows.append({
                "patient": patient, "exercise": ex_name, "side": side,
                "x": counts["x"], "y": counts["y"], "z": counts["z"],
                "closest_to_10": best_axis,
            })

df = pd.DataFrame(rows)
pd.set_option("display.width", 200)
print(df.to_string(index=False))

print("\n=== Which axis is closest to 10, per exercise? ===")
for ex in ("Ex_MS_Bracos", "Ex_MI_Pernas"):
    sub = df[df["exercise"] == ex]
    print(f"\n{ex} (n={len(sub)}):")
    print(sub["closest_to_10"].value_counts())
    for axis in ("x", "y", "z"):
        mae = (sub[axis] - EXPECTED).abs().mean()
        print(f"  axis {axis}: mean |diff| from 10 = {mae:.2f}")

df.to_csv(TEST_DIR / "axis_choice_diagnosis.csv", index=False, encoding="utf-8-sig")
print("\nSaved: test/axis_choice_diagnosis.csv")
