"""
Cohen's d and z-score of PD vs Control for every metric and exercise/limb panel, at the three
granularities (medium, small, full), with Welch's t-test p-values: radar_values.csv.

These are the values behind the radar profiles in Chapter 6 (z = difference of means divided by
the Control SD, following Zia Ur Rehman et al. 2020). The figures themselves are not drawn here.
"""
import glob
import json
import numpy as np
import pandas as pd
from scipy import stats
from participants import ANON, GROUP_MAP, PLACEMENT

# Same panel order as the Chapter 6 tables.
PANELS = [
    ("Ex_MS_Bracos", "UL", "Arms"),
    ("Ex_MI_Pernas", "LL", "Legs"),
    ("Ex_Swim_1", "LL", "S1 legs"),
    ("Ex_Swim_1", "UL", "S1 arms"),
    ("Ex_Swim_2", "LL", "S2 legs"),
    ("Ex_Swim_2", "UL", "S2 arms"),
]


def effect(pd_vals, c_vals):
    a, b = pd.Series(pd_vals).dropna(), pd.Series(c_vals).dropna()
    p = stats.ttest_ind(a, b, equal_var=False).pvalue
    diff = a.mean() - b.mean()
    d = diff / np.sqrt((a.std() ** 2 + b.std() ** 2) / 2)
    z = diff / b.std()
    return dict(n_pd=len(a), n_c=len(b), d=d, z=z, p=p)


def lr_panel_table(df, value_cols):
    """Per patient x panel, mean of right and left limb sensors (as in the small/full tables)."""
    df = df.copy()
    df["sensor_id"] = df["sensor"].astype(str).str.split("_").str[0]
    rows = []
    for patient, pg in df.groupby("patient"):
        placement, anon = PLACEMENT.get(patient), ANON.get(patient)
        if placement is None or anon not in GROUP_MAP:
            continue
        for ex, limb, label in PANELS:
            eg = pg[pg["exercise"] == ex]
            if eg.empty:
                continue
            rid = placement.get("ULR" if limb == "UL" else "LLR")
            lid = placement.get("ULL" if limb == "UL" else "LLL")
            rec = {"patient": anon, "group": GROUP_MAP[anon], "panel": label}
            for side, sid in (("R", rid), ("L", lid)):
                v = eg[eg["sensor_id"] == sid]
                for col in value_cols:
                    rec[f"{col}_{side}"] = v[col].iloc[0] if len(v) else np.nan
            for col in value_cols:
                rec[col] = np.nanmean([rec[f"{col}_R"], rec[f"{col}_L"]])
            rec["abs_ai"] = abs((rec["load_R"] - rec["load_L"]) / (rec["load_R"] + rec["load_L"]) * 100) \
                if "load" in value_cols else np.nan
            rows.append(rec)
    return pd.DataFrame(rows)


def medium_table():
    c = pd.read_csv("cycles_by_limb.csv")
    c.columns = [x.lstrip("﻿") for x in c.columns]
    c["pid"] = c["patient"].map(ANON)
    c = c[c["pid"].isin(GROUP_MAP)]
    cv = lambda x: x.std() / x.mean() * 100
    rows = []
    for ex, limb, label in PANELS:
        sub = c[(c["exercise"] == ex) & (c["limb_type"] == limb)]
        for pid, g in sub.groupby("pid"):
            rows.append(dict(patient=pid, group=GROUP_MAP[pid], panel=label,
                             stroke_time=g["duration_s"].mean(), stroke_time_cv=cv(g["duration_s"]),
                             energy=g["mechanical_load"].mean(), energy_cv=cv(g["mechanical_load"]),
                             sparc=g["sparc"].mean()))
    med = pd.DataFrame(rows)
    a = pd.read_csv("asymmetry_results.csv")
    a.columns = [x.lstrip("﻿") for x in a.columns]
    a["pid"] = a["patient"].map(ANON)
    a = a[a["pid"].isin(GROUP_MAP)]
    ex_label = {ex: lab for ex, _, lab in PANELS}
    a["panel"] = [next(l for e, lt, l in PANELS if e == ex and lt == lt_)
                  for ex, lt_ in zip(a["exercise"], a["limb_type"])]
    a["abs_ai"] = a["asymmetry_index"].abs()
    return med.merge(a[["pid", "panel", "abs_ai"]].rename(columns={"pid": "patient"}),
                     on=["patient", "panel"], how="outer").assign(
        group=lambda d: d["patient"].map(GROUP_MAP))


def small_table():
    s = pd.read_csv("summary_small.csv")
    s.columns = [x.lstrip("﻿") for x in s.columns]
    s["load"] = s["mechanical_load_mean"]
    s["load_cv"] = s["mechanical_load_std"] / s["mechanical_load_mean"] * 100
    s = s.rename(columns={"load_fatigue_slope": "load_slope", "sparc_mean": "sparc_m",
                          "avg_power_mean": "power", "dominant_frequency_mean": "dom_freq"})
    return lr_panel_table(s, ["load", "load_cv", "load_slope", "sparc_m", "power", "dom_freq"])


def full_table():
    f = pd.read_csv("full_exercise_features.csv")
    extra = []
    for path in glob.glob("Results/*/*/*_features.json"):
        d = json.load(open(path, encoding="utf-8"))
        parts = path.replace("\\", "/").split("/")
        t = d["TSFEL_Features"]
        extra.append(dict(patient=parts[-3], sensor=parts[-2], exercise=parts[-1].replace("_features.json", ""),
                          power=t.get("Magnitude_Average power"),
                          fund_freq=t.get("Magnitude_Fundamental frequency")))
    f = f.merge(pd.DataFrame(extra), on=["patient", "sensor", "exercise"], how="left")
    f = f.rename(columns={"mechanical_load": "load"})
    return lr_panel_table(f, ["load", "sparc", "power", "fund_freq"])


def compute(table, metrics):
    rows = []
    for metric_label, col in metrics:
        for _, _, panel in PANELS:
            sub = table[table["panel"] == panel]
            r = effect(sub.loc[sub.group == "PD", col], sub.loc[sub.group == "Control", col])
            rows.append(dict(metric=metric_label, panel=panel, **r))
    return pd.DataFrame(rows)


if __name__ == "__main__":
    configs = {
        "medium": (medium_table(), [
            ("Stroke time", "stroke_time"), ("Stroke time variability", "stroke_time_cv"),
            ("Energy per stroke", "energy"), ("Energy variability", "energy_cv"),
            ("Smoothness (SPARC)", "sparc"), ("Asymmetry |AI|", "abs_ai")],
            "Medium granularity (per cycle)"),
        "small": (small_table(), [
            ("Mean energy", "load"), ("Energy variability", "load_cv"),
            ("Energy trend", "load_slope"), ("Smoothness (SPARC)", "sparc_m"),
            ("Signal power", "power"), ("Dominant frequency", "dom_freq")],
            "Small granularity (250 ms windows)"),
        "full": (full_table(), [
            ("Global energy", "load"), ("Smoothness (SPARC)", "sparc"),
            ("Asymmetry |AI|", "abs_ai"), ("Signal power", "power"),
            ("Fundamental frequency", "fund_freq")],
            "Full granularity (whole exercise)"),
    }
    all_res = []
    for key, (table, metrics, label) in configs.items():
        res = compute(table, metrics)
        res.insert(0, "granularity", key)
        all_res.append(res)
    all_res = pd.concat(all_res, ignore_index=True)
    all_res.to_csv("radar_values.csv", index=False)
    print(all_res.round(3).to_string())
