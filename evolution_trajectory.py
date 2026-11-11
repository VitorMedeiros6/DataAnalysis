"""
Values behind the evolution figure of Chapter 6, Section 6.1.3 (group-average trajectory of
force across normalized cycle position, isolated arm exercise). The figure itself is not drawn.

For each participant, the cycles of the isolated arm exercise are placed on a 0-1 scale
(0 = first cycle, 1 = last), split into 10 equal bins, and the mechanical load is averaged per
group and bin.

Output:
  evolution_trajectory.csv   group, bin, bin_center, n_cycles, mean_load, sem_load
"""
import numpy as np
import pandas as pd

from participants import ANON, GROUP_MAP

N_BINS = 10

cbl = pd.read_csv("cycles_by_limb.csv")
cbl["patient"] = cbl["patient"].map(ANON).fillna(cbl["patient"])
cbl = cbl[cbl["patient"].isin(GROUP_MAP)].copy()
cbl["group"] = cbl["patient"].map(GROUP_MAP)
cbl["panel"] = cbl["exercise_label"] + " - " + cbl["limb_type"].map({"UL": "Braco", "LL": "Perna"})
sub = cbl[cbl["panel"] == "Arm exercise - Braco"].copy()

# Normalized cycle position per participant
sub["norm_pos"] = sub.groupby("patient")["cycle_number"].transform(
    lambda s: (s - s.min()) / (s.max() - s.min()) if s.max() > s.min() else np.nan
)
sub = sub.dropna(subset=["norm_pos"])

sub["bin"] = pd.cut(sub["norm_pos"], bins=N_BINS, labels=False, include_lowest=True)
agg = (sub.groupby(["group", "bin"])["mechanical_load"]
          .agg(n_cycles="count", mean_load="mean", sem_load="sem").reset_index())
agg.insert(2, "bin_center", (agg["bin"] + 0.5) / N_BINS)
agg = agg.sort_values(["group", "bin"], key=lambda c: c.map({"PD": 0, "Control": 1}) if c.name == "group" else c)

agg.to_csv("evolution_trajectory.csv", index=False)
print("Isolated arm exercise: mechanical load across normalized cycle position (mean ± SEM)")
print(agg.round(3).to_string(index=False))
print("\nSaved: evolution_trajectory.csv")
