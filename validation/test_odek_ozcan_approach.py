"""
test/ only, READ-ONLY on production data.

Replicates the Ödek & Özcan (2023) approach as closely as feasible on our
data: single fixed axis (y), 3rd-order low-pass Butterworth filter at 2Hz
(no bandpass), simple local-maxima peak detection above a threshold (no
explicit min-distance constraint, mirroring their Excel peak formula).

Compares against our current (fixed) segmentar_movimentos on the same
28 sensor/exercise cases used in the earlier diagnostics.
"""
import json
import numpy as np
import pandas as pd
from pathlib import Path
import skdh
from scipy.signal import butter, filtfilt, find_peaks

import sys
TEST_DIR = Path(__file__).resolve().parent
ROOT = TEST_DIR.parent
sys.path.insert(0, str(TEST_DIR))
sys.path.insert(0, str(ROOT))

from test_segmentation import segmentar_movimentos
from sensor_placement import PLACEMENT_FILES

PROTOCOL = json.load(open(ROOT / "data" / "tempos_protocolo.json", encoding="utf-8"))
SENSOR_DATA = ROOT / "data" / "sensor_data"

SAMPLE_PATIENTS = ["Patient 1", "Patient 2", "Patient 4", "Patient 5",
                   "Patient 12", "Patient 10", "Patient 7"]
EXPECTED = 10


def parse_ts(t_str, ref_date):
    from datetime import datetime, timedelta, timezone
    h, m, s = int(t_str.split('h')[0]), int(t_str.split('h')[1].split('m')[0]), int(t_str.split('m')[1].replace('s', ''))
    return datetime.combine(ref_date, datetime.min.time()).replace(tzinfo=timezone.utc) + timedelta(hours=h, minutes=m, seconds=s)


def odek_ozcan_peaks(df_full, h_start, h_end, fs):
    """Y-axis only, 3rd-order low-pass @2Hz, local maxima above 1sigma threshold."""
    ref_date = df_full['timestamp'].iloc[0].date()
    t0, t1 = parse_ts(h_start, ref_date), parse_ts(h_end, ref_date)
    core = df_full[(df_full['timestamp'] >= t0) & (df_full['timestamp'] <= t1)]
    if len(core) < 10:
        return None

    b, a = butter(3, 2.0 / (fs / 2), btype='low')
    y_filt = filtfilt(b, a, core['y'].values)
    threshold = y_filt.mean() + y_filt.std() * 1.0
    peaks, _ = find_peaks(y_filt, height=threshold)
    return peaks


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
                # our current (fixed) algorithm, for comparison
                segment_date = df_full['timestamp'].iloc[0].date()
                _, picos_ours, *_ = segmentar_movimentos(df_full, h_start, h_end, freq_amostragem=fs,
                                                          data_referencia=segment_date, exercise_name=ex_name)
                peaks_oo = odek_ozcan_peaks(df_full, h_start, h_end, fs)
            except Exception as e:
                print(f"[ERROR] {patient}/{sensor_filename}/{ex_name}: {e}")
                continue
            if peaks_oo is None:
                continue
            rows.append({
                "patient": patient, "exercise": ex_name, "side": side,
                "ours_detected": len(picos_ours),
                "odek_ozcan_detected": len(peaks_oo),
                "expected": EXPECTED,
            })

df = pd.DataFrame(rows)
df["ours_diff"] = df["ours_detected"] - df["expected"]
df["oo_diff"] = df["odek_ozcan_detected"] - df["expected"]
pd.set_option("display.width", 200)
print(df.to_string(index=False))
print()
print("=== Mean absolute error from expected=10 ===")
print(f"Our current algorithm:      {df['ours_diff'].abs().mean():.2f}")
print(f"Odek & Ozcan-style (y+LP2Hz): {df['oo_diff'].abs().mean():.2f}")
df.to_csv(TEST_DIR / "odek_ozcan_comparison.csv", index=False, encoding="utf-8-sig")
