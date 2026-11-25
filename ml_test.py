#!/usr/bin/env python3
"""ML honest test (needs: pip install scikit-learn pandas). For PC / GitHub Actions.
Compares a model to the bookmaker's own normalised probabilities on later matches (time split).
If the model's log-loss is NOT lower than the bookmaker's, there is no predictive signal."""
import sys, numpy as np, pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import log_loss

import glob
files = sys.argv[1:] or sorted(glob.glob("data/*.csv"))
df = pd.concat([pd.read_csv(f) for f in files]).dropna(subset=["odds_1", "result"])
df = df.sort_values(["round", "event_id"]).reset_index(drop=True)
inv = 1/df[["odds_1", "odds_X", "odds_2"]].values
book = inv/inv.sum(1, keepdims=True)
y = df["result"].map({"1": 0, "X": 1, "2": 2}).values
X = np.column_stack([df[["odds_1", "odds_X", "odds_2", "over_2.5", "under_2.5", "over_1.5", "over_3.5"]].values,
                     df["league"].astype("category").cat.codes])
cut = int(len(df)*.7)
m = HistGradientBoostingClassifier(max_depth=3, max_iter=150, learning_rate=0.05).fit(X[:cut], y[:cut])
p = m.predict_proba(X[cut:])
print("matchs train/test:", cut, len(df)-cut)
print("log-loss bookmaker (test): %.4f" % log_loss(y[cut:], book[cut:]))
print("log-loss modele    (test): %.4f" % log_loss(y[cut:], p))
print("-> le modele n'a un signal que s'il est NETTEMENT plus bas que le bookmaker.")
