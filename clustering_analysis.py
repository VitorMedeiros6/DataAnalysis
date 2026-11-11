"""
K-means clustering (k = 2) of the participants' mean cycle features, compared with the
PD/Control labels (Chapter 6, Section 6.2). Prints the adjusted Rand index (ARI), the silhouette
score and the variance explained by the first two principal components.

Output:
  clustering_pca.csv   one row per participant: group, K-means cluster and the first two principal
                       components (the values behind the clustering figure, which is not drawn)
"""
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.metrics import adjusted_rand_score, silhouette_score

from participants import ANON, GROUP_MAP

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

pca_table = pd.DataFrame({"patient": patient_features["patient"], "group": patient_features["group"],
                          "cluster": cluster_labels, "PC1": X_pca[:, 0], "PC2": X_pca[:, 1]})
pca_table.to_csv("clustering_pca.csv", index=False)
print("Saved: clustering_pca.csv")
