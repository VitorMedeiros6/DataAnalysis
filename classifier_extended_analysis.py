import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import LeaveOneOut, cross_val_predict
from sklearn.metrics import (accuracy_score, roc_auc_score, precision_score,
                              recall_score, f1_score)

from participants import ANON, GROUP_MAP

cbl = pd.read_csv("cycles_by_limb.csv")
cbl["patient"] = cbl["patient"].map(ANON).fillna(cbl["patient"])
cbl = cbl[cbl["patient"].isin(GROUP_MAP)].copy()
cbl["group"] = cbl["patient"].map(GROUP_MAP)

FEATURES = ["duration_s", "avg_velocity_ms", "peak_velocity_ms", "mechanical_load", "sparc"]
patient_features = cbl.groupby(["patient", "group"])[FEATURES].mean().reset_index().dropna()

# --- add mean |AI| (asymmetry) per patient, averaged across all panels ---
asym = pd.read_csv("asymmetry_results.csv")
asym["patient"] = asym["patient"].map(ANON).fillna(asym["patient"])
asym["abs_ai"] = asym["asymmetry_index"].abs()
asym_mean = asym.groupby("patient")["abs_ai"].mean().rename("mean_abs_ai")
patient_features = patient_features.merge(asym_mean, on="patient", how="left")

print("=== Base feature set (5 features) ===")
X5 = StandardScaler().fit_transform(patient_features[FEATURES])
y = (patient_features["group"] == "PD").astype(int).values
n = len(y)
loo = LeaveOneOut()

def evaluate(X, y, name):
    results = {}
    for model_name, clf in [
        ("Logistic Regression", LogisticRegression(max_iter=1000)),
        ("Random Forest", RandomForestClassifier(n_estimators=200, max_depth=3, random_state=0)),
    ]:
        preds = cross_val_predict(clf, X, y, cv=loo, method="predict")
        probs = cross_val_predict(clf, X, y, cv=loo, method="predict_proba")[:, 1]
        acc = accuracy_score(y, preds)
        auc = roc_auc_score(y, probs)
        prec = precision_score(y, preds, zero_division=0)
        rec = recall_score(y, preds, zero_division=0)
        f1 = f1_score(y, preds, zero_division=0)
        print(f"  [{name}] {model_name}: acc={acc:.3f} auc={auc:.3f} precision(PD)={prec:.3f} recall(PD)={rec:.3f} f1(PD)={f1:.3f}")
        results[model_name] = dict(acc=acc, auc=auc, prec=prec, rec=rec, f1=f1, probs=probs)
    return results

res5 = evaluate(X5, y, "5-feature")

print()
print("=== Random Forest feature importance (5-feature, fit on full data) ===")
rf_full = RandomForestClassifier(n_estimators=200, max_depth=3, random_state=0).fit(X5, y)
for f, imp in sorted(zip(FEATURES, rf_full.feature_importances_), key=lambda x: -x[1]):
    print(f"  {f:20s} {imp:.3f}")

print()
print("=== Logistic Regression coefficients (5-feature, fit on full data, standardized X) ===")
lr_full = LogisticRegression(max_iter=1000).fit(X5, y)
for f, coef in sorted(zip(FEATURES, lr_full.coef_[0]), key=lambda x: -abs(x[1])):
    print(f"  {f:20s} {coef:+.3f}")

print()
print("=== Permutation test: is LOO AUC significantly different from chance? ===")
rng = np.random.default_rng(0)
n_perm = 1000
for model_name, clf in [
    ("Logistic Regression", LogisticRegression(max_iter=1000)),
    ("Random Forest", RandomForestClassifier(n_estimators=200, max_depth=3, random_state=0)),
]:
    real_probs = cross_val_predict(clf, X5, y, cv=loo, method="predict_proba")[:, 1]
    real_auc = roc_auc_score(y, real_probs)
    perm_aucs = []
    for i in range(n_perm):
        y_perm = rng.permutation(y)
        try:
            probs = cross_val_predict(clf, X5, y_perm, cv=loo, method="predict_proba")[:, 1]
            perm_aucs.append(roc_auc_score(y_perm, probs))
        except Exception:
            continue
    perm_aucs = np.array(perm_aucs)
    p_value = (np.sum(perm_aucs >= real_auc) + 1) / (len(perm_aucs) + 1)
    print(f"  {model_name}: real AUC={real_auc:.3f}, permutation-null mean={perm_aucs.mean():.3f} "
          f"(sd={perm_aucs.std():.3f}), p={p_value:.3f}")

print()
print("=== Extended feature set: 5 features + mean |AI| (asymmetry) ===")
patient_features_6 = patient_features.dropna(subset=["mean_abs_ai"])
print(f"  N with asymmetry data = {len(patient_features_6)} "
      f"({(patient_features_6['group']=='PD').sum()} PD, {(patient_features_6['group']=='Control').sum()} Control)")
FEATURES6 = FEATURES + ["mean_abs_ai"]
X6 = StandardScaler().fit_transform(patient_features_6[FEATURES6])
y6 = (patient_features_6["group"] == "PD").astype(int).values
loo6 = LeaveOneOut()

def evaluate6(X, y):
    for model_name, clf in [
        ("Logistic Regression", LogisticRegression(max_iter=1000)),
        ("Random Forest", RandomForestClassifier(n_estimators=200, max_depth=3, random_state=0)),
    ]:
        preds = cross_val_predict(clf, X, y, cv=LeaveOneOut(), method="predict")
        probs = cross_val_predict(clf, X, y, cv=LeaveOneOut(), method="predict_proba")[:, 1]
        acc = accuracy_score(y, preds)
        auc = roc_auc_score(y, probs)
        print(f"  [6-feature] {model_name}: acc={acc:.3f} auc={auc:.3f} (baseline={max(y.mean(),1-y.mean()):.3f}, n={len(y)})")

evaluate6(X6, y6)

print()
print("=== Random Forest feature importance (6-feature incl. asymmetry) ===")
rf6 = RandomForestClassifier(n_estimators=200, max_depth=3, random_state=0).fit(X6, y6)
for f, imp in sorted(zip(FEATURES6, rf6.feature_importances_), key=lambda x: -x[1]):
    print(f"  {f:20s} {imp:.3f}")
