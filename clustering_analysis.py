"""
K-means clustering (k = 2) of the participants' mean cycle features, compared with the
PD/Control labels (Chapter 6, Section 6.2). Prints the adjusted Rand index (ARI), the silhouette
score and the variance explained by the first two principal components.
"""
import json
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.metrics import adjusted_rand_score, silhouette_score

with open("participants.json", encoding="utf-8") as f:
    ANON = {pid: pid for pid in json.load(f)}

PD_ALL = ['Patient 1','Patient 2','Patient 3','Patient 4','Patient 5','Patient 6','Patient 7',
          'Patient 9','Patient 10','Patient 12','Patient 14','Patient 15','Patient 16',
          'Patient 17','Patient 18','Patient 19','Patient 20','Patient 21','Patient 22']
CONTROL_ALL = ['Control 1','Control 3','Control 4','Control 5','Control 6','Control 7',
               'Control 8','Control 9','Control 10','Control 11']
GROUP_MAP = {p: 'PD' for p in PD_ALL}
GROUP_MAP.update({p: 'Control' for p in CONTROL_ALL})

cbl = pd.read_csv("cycles_by_limb.csv")
cbl["patient"] = cbl["patient"].map(ANON).fillna(cbl["patient"])
cbl = cbl[cbl["patient"].isin(GROUP_MAP)].copy()
cbl["group"] = cbl["patient"].map(GROUP_MAP)

FEATURES = ["duration_s", "avg_velocity_ms", "peak_velocity_ms", "mechanical_load", "sparc"]
patient_features = cbl.groupby(["patient", "group"])[FEATURES].mean().reset_index().dropna()

X = StandardScaler().fit_transform(patient_features[FEATURES])
km = KMeans(n_clusters=2, n_init=10, random_state=0)
cluster_labels = km.fit_predict(X)

ari = adjusted_rand_score(patient_features["group"].map({"PD": 0, "Control": 1}), cluster_labels)
sil = silhouette_score(X, cluster_labels)
pca = PCA(n_components=2, random_state=0)
X_pca = pca.fit_transform(X)
var_explained = pca.explained_variance_ratio_.sum() * 100

print(f"N patients = {len(patient_features)} "
      f"({(patient_features['group'] == 'PD').sum()} PD, {(patient_features['group'] == 'Control').sum()} Control)")
print(f"ARI = {ari:.3f}  silhouette = {sil:.3f}  variance explained (2 PCs) = {var_explained:.0f}%")
