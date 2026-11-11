"""
Table 4.1 (Chapter 4): detected vs expected cycle counts with the production detection.

Calls segmentar_movimentos from data_analysis_medium.py (the function that builds
cycles_medium.csv, not a copy) on every window in validation/test_protocol.json. The limb of each
sensor comes from data/participants.json, exactly as during extraction, so the fixed-axis primary
method is used whenever it finds at least 3 peaks and the fallback method otherwise.

Prints one row per sensor and exercise (method used, detected, expected, difference) and the
summary statistics quoted in Chapter 4: mean absolute error, maximum error and the share of cases
within +/-1 cycle. Windows without "expected_cycles" are listed but left out of the statistics.

Output:
  validation/cycle_validation.csv
"""
import contextlib
import io
import json
import re
import sys
from pathlib import Path

import pandas as pd
import skdh

TEST_DIR = Path(__file__).resolve().parent
ROOT = TEST_DIR.parent
sys.path.insert(0, str(ROOT))

import data_analysis_medium as production  # noqa: E402

PROTOCOL = json.load(open(TEST_DIR / "test_protocol.json", encoding="utf-8"))
SENSOR_DATA = ROOT / "data" / "sensor_data"

rows = []
for patient, sensors in PROTOCOL.items():
    for file_name, exercises in sensors.items():
        path = SENSOR_DATA / patient / file_name
        if not path.exists():
            print(f"Skipped {patient}/{file_name}: recording not found")
            continue
        data = skdh.io.ReadCwa().predict(file=str(path))
        df = pd.DataFrame({"timestamp": pd.to_datetime(data["time"], unit="s", utc=True),
                           "x": data["accel"][:, 0], "y": data["accel"][:, 1], "z": data["accel"][:, 2]})
        sensor = Path(file_name).stem
        for exercise, window in exercises.items():
            limb = production._limb_type_for_sensor(patient, sensor.split("_")[0], exercise)
            log = io.StringIO()
            with contextlib.redirect_stdout(log):
                cycles = production.segmentar_movimentos(
                    df, window["start_time"], window["end_time"], freq_amostragem=data["fs"],
                    data_referencia=df["timestamp"].iloc[0].date(),
                    exercise_name=exercise, limb_type=limb)
            # segmentar_movimentos reports the signal it used, e.g. "(sinal: fixed_y)"
            signal = re.search(r"sinal: (\S+)\)", log.getvalue())
            method = "fixed axis" if signal and signal.group(1).startswith("fixed_") else "fallback"
            expected = window.get("expected_cycles")
            rows.append({
                "participant": patient, "sensor": sensor, "exercise": exercise, "limb": limb,
                "method": method, "detected": len(cycles), "expected": expected,
                "difference": len(cycles) - expected if expected is not None else None,
            })

table = pd.DataFrame(rows)
print(table.to_string(index=False))

known = table.dropna(subset=["difference"])
if len(known):
    err = known["difference"].abs()
    within = int((err <= 1).sum())
    print(f"\nCases with an expected count: {len(known)}")
    print(f"Mean absolute error: {err.mean():.2f} cycles")
    print(f"Maximum error:       {int(err.max())} cycles")
    print(f"Within +/-1 cycle:   {within} of {len(known)} ({100 * within / len(known):.0f}%)")

table.to_csv(TEST_DIR / "cycle_validation.csv", index=False, encoding="utf-8-sig")
print("\nSaved: validation/cycle_validation.csv")
