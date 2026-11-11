import json
import pandas as pd, numpy as np
from scipy import stats
from sensor_placement import PLACEMENT
from build_isolated_summary import EXERCISE_LIMB_GROUPS

with open("participants.json", encoding="utf-8") as f:
    ANON = {pid: pid for pid in json.load(f)}

PD_ALL = ['Patient 1','Patient 2','Patient 3','Patient 4','Patient 5',
          'Patient 6','Patient 7','Patient 9','Patient 10','Patient 12',
          'Patient 14','Patient 15','Patient 16','Patient 17','Patient 18',
          'Patient 19','Patient 20','Patient 21','Patient 22']
CONTROL_ALL = ['Control 1','Control 3','Control 4','Control 5','Control 6',
               'Control 7','Control 8','Control 9','Control 10','Control 11']
GROUP_MAP = {p: 'PD' for p in PD_ALL}
GROUP_MAP.update({p: 'Control' for p in CONTROL_ALL})

df = pd.read_csv('full_exercise_features.csv')
df['sensor_id'] = df['sensor'].astype(str).str.split('_').str[0]

rows = []
for patient, pgroup in df.groupby('patient'):
    placement = PLACEMENT.get(patient)
    anon = ANON.get(patient)
    if placement is None or anon is None or anon not in GROUP_MAP:
        continue
    group = GROUP_MAP[anon]
    for exercise, limb_type, label in EXERCISE_LIMB_GROUPS:
        egroup = pgroup[pgroup['exercise'] == exercise]
        if egroup.empty:
            continue
        right_id = placement.get('ULR' if limb_type == 'UL' else 'LLR')
        left_id = placement.get('ULL' if limb_type == 'UL' else 'LLL')
        rvals = egroup[egroup['sensor_id'] == right_id]
        lvals = egroup[egroup['sensor_id'] == left_id]
        rec = {'patient': anon, 'group': group, 'panel': label}
        if len(rvals):
            rec['load_R'] = rvals['mechanical_load'].iloc[0]
            rec['sparc_R'] = rvals['sparc'].iloc[0]
        if len(lvals):
            rec['load_L'] = lvals['mechanical_load'].iloc[0]
            rec['sparc_L'] = lvals['sparc'].iloc[0]
        rows.append(rec)

long_df = pd.DataFrame(rows)
long_df['load_mean'] = long_df[['load_R','load_L']].mean(axis=1)
long_df['sparc_mean'] = long_df[['sparc_R','sparc_L']].mean(axis=1)
long_df['load_AI'] = (long_df['load_R']-long_df['load_L'])/(long_df['load_R']+long_df['load_L'])*100
long_df['load_AI_abs'] = long_df['load_AI'].abs()

PANEL_DISPLAY = {'Arm':'Arms (isolated)','Leg':'Legs (isolated)','Swim 1 - Leg':'Swim 1 (Legs)',
                 'Swim 1 - Arm':'Swim 1 (Arms)','Swim 2 - Leg':'Swim 2 (Legs)','Swim 2 - Arm':'Swim 2 (Arms)'}

def teste(a,b):
    a,b = pd.Series(a).dropna(), pd.Series(b).dropna()
    if len(a)<2 or len(b)<2: return None
    t,p = stats.ttest_ind(a,b,equal_var=False)
    d = (a.mean()-b.mean())/np.sqrt((a.std()**2+b.std()**2)/2)
    return len(a),a.mean(),len(b),b.mean(),t,p,d

print("=== FULL-WINDOW (true whole-exercise TSFEL) - Absolute Intensity ===")
for _,_,label in EXERCISE_LIMB_GROUPS:
    sub = long_df[long_df['panel']==label]
    for metric, col in [('Mechanical load','load_mean'), ('SPARC','sparc_mean')]:
        r = teste(sub[sub['group']=='PD'][col], sub[sub['group']=='Control'][col])
        if r:
            n1,m1,n2,m2,t,p,d = r
            flag='*' if p<0.05 else ' '
            print(f"{PANEL_DISPLAY[label]:16s} {metric:16s} n_PD={n1:2d} {m1:9.2f}  n_C={n2:2d} {m2:9.2f}  t={t:+.2f} p={p:.3f}{flag} d={d:+.2f}")

print()
print("=== FULL-WINDOW - Bilateral Asymmetry (|AI| of mechanical load) ===")
for _,_,label in EXERCISE_LIMB_GROUPS:
    sub = long_df[long_df['panel']==label]
    r = teste(sub[sub['group']=='PD']['load_AI_abs'], sub[sub['group']=='Control']['load_AI_abs'])
    if r:
        n1,m1,n2,m2,t,p,d = r
        flag='*' if p<0.05 else ' '
        print(f"{PANEL_DISPLAY[label]:16s} n_PD={n1:2d} {m1:6.2f}%  n_C={n2:2d} {m2:6.2f}%  t={t:+.2f} p={p:.3f}{flag} d={d:+.2f}")

long_df.to_csv('full_window_panel_data.csv', index=False)
