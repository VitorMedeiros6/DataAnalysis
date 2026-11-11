"""
test/ only, READ-ONLY on production data.

Applies the Odek & Ozcan-style detection (fixed axis per limb: Y for arm
sensors, X for leg sensors; 3rd-order low-pass Butterworth @2Hz; simple
threshold peak detection) to 5 NEW patients (not tested before), across
ALL FOUR exercises, and compares against our current production algorithm.

Ex_MS_Bracos / Ex_MI_Pernas have a known expected count (10, per protocol).
Ex_Swim_1 / Ex_Swim_2 have no prescribed count, so both arm and leg sensors
are evaluated during swim windows (limb still moves, no "expected" column).
"""
import json
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta, timezone
import skdh
from scipy.signal import butter, filtfilt, find_peaks

import sys
TEST_DIR = Path(__file__).resolve().parent
ROOT = TEST_DIR.parent
sys.path.insert(0, str(TEST_DIR))
sys.path.insert(0, str(ROOT))

from test_segmentation import segmentar_movimentos
from participants import PLACEMENT_FILES

PROTOCOL = json.load(open(ROOT / "data" / "tempos_protocolo.json", encoding="utf-8"))
SENSOR_DATA = ROOT / "data" / "sensor_data"

NEW_PATIENTS = ["Patient 15", "Patient 14", "Patient 20",
                "Patient 6", "Patient 16"]

EXERCISES = ["Ex_MS_Bracos", "Ex_MI_Pernas", "Ex_Swim_1", "Ex_Swim_2"]
EXPECTED = {"Ex_MS_Bracos": 10, "Ex_MI_Pernas": 10, "Ex_Swim_1": None, "Ex_Swim_2": None}


def parse_ts(t_str, ref_date):
    h, m, s = int(t_str.split('h')[0]), int(t_str.split('h')[1].split('m')[0]), int(t_str.split('m')[1].replace('s', ''))
    return datetime.combine(ref_date, datetime.min.time()).replace(tzinfo=timezone.utc) + timedelta(hours=h, minutes=m, seconds=s)


def oo_peak_count(df_full, h_start, h_end, fs, axis):
    ref_date = df_full['timestamp'].iloc[0].date()
    t0, t1 = parse_ts(h_start, ref_date), parse_ts(h_end, ref_date)
    core = df_full[(df_full['timestamp'] >= t0) & (df_full['timestamp'] <= t1)]
    if len(core) < 10:
        return None
    b, a = butter(3, 2.0 / (fs / 2), btype='low')
    filt = filtfilt(b, a, core[axis].values)
    thr = filt.mean() + filt.std() * 1.0
    peaks, _ = find_peaks(filt, height=thr)
    return len(peaks)


rows = []
for patient in NEW_PATIENTS:
    placement = PLACEMENT_FILES.get(patient)
    proto = PROTOCOL.get(patient)
    if placement is None or proto is None:
        print(f"[SKIP] {patient}: no placement/protocol")
        continue

    for ex_name in EXERCISES:
        # In swim, both limb types are relevant; in isolated exercises, only one.
        limb_types = ["UL", "LL"] if ex_name.startswith("Ex_Swim") else (["UL"] if ex_name == "Ex_MS_Bracos" else ["LL"])

        for limb in limb_types:
            axis = "y" if limb == "UL" else "x"  # Odek&Ozcan-style fixed axis per limb
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
                    segment_date = df_full['timestamp'].iloc[0].date()
                    _, picos_ours, *_ = segmentar_movimentos(df_full, h_start, h_end, freq_amostragem=fs,
                                                              data_referencia=segment_date, exercise_name=ex_name)
                    oo_count = oo_peak_count(df_full, h_start, h_end, fs, axis)
                except Exception as e:
                    print(f"[ERROR] {patient}/{sensor_filename}/{ex_name}: {e}")
                    continue
                if oo_count is None:
                    continue

                exp = EXPECTED[ex_name]
                rows.append({
                    "patient": patient,
                    "exercise": ex_name,
                    "limb": "Arm" if limb == "UL" else "Leg",
                    "side": side,
                    "expected": exp,
                    "ours": len(picos_ours),
                    "ours_diff": (len(picos_ours) - exp) if exp else None,
                    "odek_ozcan": oo_count,
                    "oo_diff": (oo_count - exp) if exp else None,
                    "axis_used": axis,
                })

df = pd.DataFrame(rows)
if df.empty:
    print("No participant in NEW_PATIENTS has both a recording and protocol times: nothing to compare.")
    sys.exit(0)
pd.set_option("display.width", 220)
pd.set_option("display.max_rows", None)
print(df.to_string(index=False))

df.to_csv(TEST_DIR / "odek_ozcan_5patients_all_ex.csv", index=False, encoding="utf-8-sig")
print(f"\nSaved: test/odek_ozcan_5patients_all_ex.csv ({len(df)} rows)")

print("\n=== Mean |diff| where expected is known (Ex_MS_Bracos / Ex_MI_Pernas) ===")
sub = df.dropna(subset=["ours_diff"])
print(f"Our current algorithm: {sub['ours_diff'].abs().mean():.2f}")
print(f"Odek & Ozcan-style:     {sub['oo_diff'].abs().mean():.2f}")
