"""Can we predict, per spectrum, whether InstaNovo+ refinement will help?

Hand-written gates capture little of what is available (section 19: the best deployable
rule reaches +0.0010 against an oracle bound of +0.0086). Refinement flips ~1.24% of
spectra from wrong to right and ~0.85% the other way, so the decision is concentrated in
about 2% of the data. That is a small, well-posed supervised problem.

Three choices keep the estimate honest:

* only features available at inference are used -- the predicted peptide, the model's own
  log-probability, the precursor, and the organism sampled. Nothing derived from the
  answer;
* the classifier is trained only on spectra where refinement *changed* the outcome, since
  the other 98% carry no signal about which choice is better;
* it is evaluated on held-out species, so the reported gain is cross-organism rather than
  a within-distribution fit.

Usage: refinement_predictor.py <extract-dir>
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

DATA = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
CORRECT = ["exact", "mass"]
MAMMALS = {"H.-sapiens", "Mus-musculus"}

# Held out for evaluation: a mammal, an archaeon, a plant and the hardest species, so the
# test side spans kingdoms rather than being a random slice of one distribution.
HELD_OUT = {"H.-sapiens", "Methanosarcina-mazei", "Solanum-lycopersicum", "Candidatus-endoloripes"}

gt = pd.read_csv(DATA / "gt_beam10.csv")
refined = pd.read_csv(DATA / "mode_beam10_refined.csv", usecols=["spectrum_id", "match_type"])
predicted = pd.read_csv(DATA / "mode_beam10.csv")
logprobs = pd.read_csv(DATA / "logprobs_beam10.csv")
spectra = pd.read_csv(DATA / "spectrum_features.csv", usecols=["spectrum_id", "precursor_mz"])

df = pd.DataFrame({
    "spectrum_id": gt["spectrum_id"],
    "collection": gt["collection"],
    "base_ok": gt["match_type"].isin(CORRECT).values,
    "refined_ok": refined["match_type"].isin(CORRECT).values,
    "sequence": predicted["peptidoform"].values,
})

if "scan_number" in logprobs.columns:
    logprobs = logprobs.rename(columns={"scan_number": "spectrum_id"})
else:
    logprobs["spectrum_id"] = logprobs["spectrum_id"].astype(str).str.rsplit(":", n=1).str[-1].astype(int)
df = df.merge(logprobs[["spectrum_id", "log_probs"]], on="spectrum_id", how="left")
df = df.merge(spectra, on="spectrum_id", how="left")

# --- features, all knowable without the answer -------------------------------------

def bare(sequence: object) -> str:
    return re.sub(r"\[UNIMOD:\d+\]|-", "", sequence) if isinstance(sequence, str) else ""


bare_sequence = df["sequence"].map(bare)
df["pred_len"] = bare_sequence.str.len()
df["log_prob"] = df["log_probs"]
df["mammal"] = df["collection"].isin(MAMMALS).astype(int)
df["n_mods"] = df["sequence"].fillna("").str.count(r"\[UNIMOD:")
df["has_nterm_mod"] = df["sequence"].fillna("").str.match(r"^\[UNIMOD:").astype(int)
# Residues whose modification state refinement most often revises.
for residue in ("M", "N", "Q", "C"):
    df[f"n_{residue}"] = bare_sequence.str.count(residue)
df["mods_per_residue"] = df["n_mods"] / df["pred_len"].clip(lower=1)
df["logprob_per_residue"] = df["log_prob"] / df["pred_len"].clip(lower=1)

FEATURES = ["pred_len", "log_prob", "mammal", "n_mods", "has_nterm_mod",
            "n_M", "n_N", "n_Q", "n_C", "mods_per_residue", "logprob_per_residue",
            "precursor_mz"]

df["helps"] = df["refined_ok"] & ~df["base_ok"]
df["hurts"] = ~df["refined_ok"] & df["base_ok"]
df["changed"] = df["helps"] | df["hurts"]
df = df.dropna(subset=FEATURES)

print(f"spectra: {len(df):,}")
print(f"  refinement helps : {df['helps'].sum():,} ({df['helps'].mean():.2%})")
print(f"  refinement hurts : {df['hurts'].sum():,} ({df['hurts'].mean():.2%})")
print(f"  no change        : {(~df['changed']).mean():.2%}")

test = df[df["collection"].isin(HELD_OUT)]
train = df[~df["collection"].isin(HELD_OUT)]
train_changed = train[train["changed"]]
print(f"\ntrain species: {sorted(set(train['collection']))}")
print(f"held-out species: {sorted(HELD_OUT)}")
print(f"training rows (changed only): {len(train_changed):,}  "
      f"({train_changed['helps'].mean():.1%} of them 'helps')")
print(f"evaluation rows: {len(test):,}")

X_train = train_changed[FEATURES].to_numpy(dtype=float)
y_train = train_changed["helps"].to_numpy(dtype=int)
X_test = test[FEATURES].to_numpy(dtype=float)

models = {}
scaler = StandardScaler().fit(X_train)
logistic = LogisticRegression(max_iter=2000, class_weight="balanced")
logistic.fit(scaler.transform(X_train), y_train)
models["logistic regression"] = logistic.predict_proba(scaler.transform(X_test))[:, 1]

trees = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.1, random_state=0)
trees.fit(X_train, y_train)
models["gradient boosting"] = trees.predict_proba(X_test)[:, 1]

# --- evaluation on the held-out species ---------------------------------------------

base_ok = test["base_ok"].to_numpy()
refined_ok = test["refined_ok"].to_numpy()
never, always = base_ok.mean(), refined_ok.mean()
oracle = (base_ok | refined_ok).mean()

print("\nheld-out baselines")
print(f"  never refine : {never:.4f}")
print(f"  always refine: {always:.4f}  ({always - never:+.4f})")
print(f"  skip mammals : {np.where(test['mammal'] == 0, refined_ok, base_ok).mean():.4f}")
print(f"  oracle gate  : {oracle:.4f}  ({oracle - always:+.4f} over always)")

print("\nlearned gate: refine when the predicted probability of helping exceeds a threshold\n")
print(f"{'model':22}{'threshold':>10}{'refined %':>11}{'precision':>11}{'vs always':>11}")
best = None
for name, probability in models.items():
    for threshold in (0.3, 0.4, 0.5, 0.6, 0.7):
        gate = probability >= threshold
        precision = np.where(gate, refined_ok, base_ok).mean()
        print(f"{name:22}{threshold:>10.2f}{gate.mean() * 100:>11.1f}{precision:>11.4f}{precision - always:>+11.4f}")
        if best is None or precision > best[2]:
            best = (name, threshold, precision, gate.mean())

name, threshold, precision, share = best
print(f"\nbest: {name} at threshold {threshold:.2f}")
print(f"  precision {precision:.4f} against {always:.4f} for always-refine ({precision - always:+.4f})")
print(f"  refining {share:.1%} of spectra")
if oracle > always:
    print(f"  captures {(precision - always) / (oracle - always):.1%} of the gap to the oracle bound")

importance = pd.Series(logistic.coef_[0], index=FEATURES).sort_values(key=abs, ascending=False)
print("\nlogistic coefficients (standardised; positive favours refining)")
print(importance.round(3).to_string())
