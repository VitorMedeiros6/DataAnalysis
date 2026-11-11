"""
Leave-one-out classification of PD vs Control from the participants' mean cycle features
(Chapter 6, Section 6.2.1): accuracy, ROC AUC and confusion matrix for logistic regression and
random forest, plus random-forest feature importances.

Output:
  classifier_roc_points.csv   the ROC curve of each model (the values behind the classifier
                              figure, which is not drawn)
"""
import pandas as pd, numpy as np
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import LeaveOneOut, cross_val_predict
from sklearn.metrics import accuracy_score, roc_auc_score, confusion_matrix, roc_curve

from participants import ANON, GROUP_MAP

cbl = pd.read_csv('cycles_by_limb.csv')
cbl['patient'] = cbl['patient'].map(ANON).fillna(cbl['patient'])
cbl = cbl[cbl['patient'].isin(GROUP_MAP)].copy()
cbl['group'] = cbl['patient'].map(GROUP_MAP)

FEATURES = ['duration_s', 'avg_velocity_ms', 'peak_velocity_ms', 'mechanical_load', 'sparc']
patient_features = cbl.groupby(['patient', 'group'])[FEATURES].mean().reset_index().dropna()

X = StandardScaler().fit_transform(patient_features[FEATURES])
y = (patient_features['group'] == 'PD').astype(int).values
n = len(y)
print(f"N patients = {n} ({y.sum()} PD, {n-y.sum()} Control)")
print(f"Baseline (majority class) accuracy = {max(y.mean(), 1-y.mean()):.3f}")
print()

loo = LeaveOneOut()
roc_rows = []

for name, clf in [
    ("Logistic Regression", LogisticRegression(max_iter=1000)),
    ("Random Forest (n=200)", RandomForestClassifier(n_estimators=200, max_depth=3, random_state=0)),
]:
    preds = cross_val_predict(clf, X, y, cv=loo, method='predict')
    try:
        probs = cross_val_predict(clf, X, y, cv=loo, method='predict_proba')[:, 1]
        auc = roc_auc_score(y, probs)
        fpr, tpr, thresholds = roc_curve(y, probs)
        roc_rows += [{'model': name, 'threshold': t, 'fpr': f, 'tpr': r}
                     for t, f, r in zip(thresholds, fpr, tpr)]
    except Exception:
        auc = float('nan')
    acc = accuracy_score(y, preds)
    cm = confusion_matrix(y, preds)
    print(f"=== {name} (Leave-One-Out CV) ===")
    print(f"  Accuracy = {acc:.3f}  (baseline = {max(y.mean(),1-y.mean()):.3f})")
    print(f"  ROC AUC  = {auc:.3f}")
    print(f"  Confusion matrix [rows=true Control/PD, cols=pred Control/PD]:\n{cm}")
    print()

# Feature importance for Random Forest (fit on full data, for reference only)
rf_full = RandomForestClassifier(n_estimators=200, max_depth=3, random_state=0).fit(X, y)
print("Random Forest feature importances (fit on full data, descriptive only):")
for f, imp in sorted(zip(FEATURES, rf_full.feature_importances_), key=lambda x: -x[1]):
    print(f"  {f:20s} {imp:.3f}")

pd.DataFrame(roc_rows).to_csv("classifier_roc_points.csv", index=False)
print()
print("Saved: classifier_roc_points.csv")
