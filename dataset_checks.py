"""
Dataset checks behind Chapter 3 (Study Population; Data Integrity and Validation).

Prints:
  1. Cohort: participants per group in data/participants.json, and who is excluded and why.
  2. Exercise completeness: which of the four exercises each analysed participant has a window
     for in data/tempos_protocolo.json, and which participants miss one.
  3. Shared recordings: participants whose .cwa files are byte-identical (SHA-256 of the file),
     and whether the exercise windows annotated for those files are also identical.
  4. Cycles per participant: rows of cycles_by_limb.csv (limb-matched cycles used in Chapter 6).

Needs data/sensor_data/, data/tempos_protocolo.json, data/participants.json and
cycles_by_limb.csv (built by `make tables`).

Output:
  dataset_checks.csv   one row per participant in data/participants.json
"""
import hashlib
import json
from collections import defaultdict
from itertools import combinations
from pathlib import Path

import pandas as pd

from participants import PARTICIPANTS, EXCLUDED, PD_ALL, CONTROL_ALL, GROUP_MAP
from build_isolated_summary import EXERCISE_LABEL

SENSOR_DATA = Path("data/sensor_data")
EXERCISES = list(EXERCISE_LABEL)

with open("data/tempos_protocolo.json", encoding="utf-8") as f:
    protocol = json.load(f)

# 1. Cohort ---------------------------------------------------------------------------------
print("=== 1. Cohort (data/participants.json) ===")
for group in ("PD", "Control"):
    listed = [p for p, e in PARTICIPANTS.items() if e["group"] == group]
    print(f"  {group}: {len(listed)} listed, {len(listed) - len([p for p in listed if p in EXCLUDED])} analysed")
print(f"  Analysed: {len(GROUP_MAP)} ({len(PD_ALL)} PD, {len(CONTROL_ALL)} Control)")
for p, reason in EXCLUDED.items():
    print(f"  Excluded: {p} ({reason})")

# 2. Exercise completeness ------------------------------------------------------------------
print("\n=== 2. Exercise completeness (windows in data/tempos_protocolo.json) ===")
exercises_of = {}
for p in PARTICIPANTS:
    sensors = protocol.get(p, {})
    exercises_of[p] = [ex for ex in EXERCISES if any(ex in windows for windows in sensors.values())]
in_protocol = [p for p in GROUP_MAP if protocol.get(p)]
without = [p for p in GROUP_MAP if not protocol.get(p)]
if without:
    print(f"  No protocol times (not checked): {', '.join(without)}")
complete = [p for p in in_protocol if len(exercises_of[p]) == len(EXERCISES)]
print(f"  Analysed participants with all {len(EXERCISES)} exercises: {len(complete)} of {len(in_protocol)}")
for p in in_protocol:
    missing = [ex for ex in EXERCISES if ex not in exercises_of[p]]
    if missing:
        print(f"  {p}: missing {', '.join(missing)}")

# 3. Shared recordings ----------------------------------------------------------------------
print("\n=== 3. Shared recordings (byte-identical .cwa files) ===")
owners = defaultdict(list)        # file hash -> [(participant, file name)]
n_files = {}
for p in PARTICIPANTS:
    files = sorted((SENSOR_DATA / p).glob("*.cwa"))
    n_files[p] = len(files)
    for path in files:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        owners[h.hexdigest()].append((p, path.name))

shared = defaultdict(list)        # (participant A, participant B) -> [file name in A]
for entries in owners.values():
    for (pa, fa), (pb, fb) in combinations(entries, 2):
        if pa != pb:
            key = tuple(sorted((pa, pb)))
            shared[key].append(fa if key[0] == pa else fb)

shares_with = defaultdict(list)
if not shared:
    print("  No two participants share a recording.")
for (pa, pb), files in sorted(shared.items()):
    same_windows = all(protocol.get(pa, {}).get(f) == protocol.get(pb, {}).get(f) for f in files)
    print(f"  {pa} and {pb}: {len(files)} identical file(s); exercise windows "
          f"{'identical' if same_windows else 'different'}")
    shares_with[pa].append(pb)
    shares_with[pb].append(pa)

# 4. Cycles per participant -----------------------------------------------------------------
print("\n=== 4. Cycles per participant (cycles_by_limb.csv) ===")
cbl = pd.read_csv("cycles_by_limb.csv", encoding="utf-8-sig")
cycles = cbl[cbl["patient"].isin(GROUP_MAP)].groupby("patient").size()
if len(cycles):
    print(f"  {len(cycles)} participants; min {cycles.min()} ({cycles.idxmin()}), "
          f"max {cycles.max()} ({cycles.idxmax()})")

rows = [{
    "participant": p,
    "group": e["group"],
    "excluded": EXCLUDED.get(p, ""),
    "cwa_files": n_files[p],
    "exercises_with_windows": len(exercises_of[p]),
    "missing_exercises": ", ".join(ex for ex in EXERCISES if ex not in exercises_of[p]),
    "limb_cycles": int(cycles.get(p, 0)),
    "shares_recording_with": ", ".join(shares_with.get(p, [])),
} for p, e in PARTICIPANTS.items()]
pd.DataFrame(rows).to_csv("dataset_checks.csv", index=False)
print("\nSaved: dataset_checks.csv")
