"""Does a stochastic mode's repeatability predict whether its answer is right?

Diffusion sampling runs unseeded, so InstaNovo+ gives a different answer on repeated
runs of the same spectrum. That instability is usually treated as a nuisance. Here it is
treated as a signal: if the runs agree on a spectrum, is that answer more likely correct?

If so it is an abstention rule that needs no model change and no labels -- run the model
n times and keep what it repeats. The cost is n inference passes, so the question is
whether the retained subset is enough better to justify them.

What this measures is sensitivity to decoding randomness, not independent confidence:
repeated runs of one model share its biases, so agreement is repeatability, not
corroboration.

Usage: stability.py <extract-dir> [mode]
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
MODE = sys.argv[2] if len(sys.argv) > 2 else "diffusion_only"
CORRECT = ["exact", "mass"]

# The primary run plus its three replicates.
primary = pd.read_csv(DATA / f"mode_{MODE}.csv", usecols=["spectrum_id", "peptidoform", "match_type"])
runs = [primary] + [
    pd.read_csv(DATA / f"rep_{MODE}_rep{i}.csv", usecols=["spectrum_id", "peptidoform", "match_type"])
    for i in (1, 2, 3)
]
for i, run in enumerate(runs):
    if not run["spectrum_id"].equals(runs[0]["spectrum_id"]):
        raise SystemExit(f"run {i} is not row-aligned with the first")

n_runs = len(runs)
df = pd.DataFrame({"spectrum_id": runs[0]["spectrum_id"]})
for i, run in enumerate(runs):
    # A handful of predictions are unparseable and arrive as null; they are their own
    # category rather than a shared value, so they must not count as agreement.
    df[f"pred_{i}"] = (run["peptidoform"].astype(str).str.replace("-", "", regex=False)
                       .fillna("").values)
    df[f"ok_{i}"] = run["match_type"].isin(CORRECT).values

prediction_columns = [f"pred_{i}" for i in range(n_runs)]
predictions = df[prediction_columns].to_numpy()


def largest_agreeing_group(row) -> int:
    """How many runs produced the single most common answer. Missing answers do not agree."""
    answers = [value for value in row if value]
    return max(Counter(answers).values()) if answers else 0


df["agreement"] = np.fromiter((largest_agreeing_group(row) for row in predictions),
                              dtype=int, count=len(df))
df["distinct"] = df[prediction_columns].nunique(axis=1)
# Correctness of the primary run: the answer a single ordinary run would have given.
df["correct"] = df["ok_0"]

total = len(df)
print(f"mode: {MODE}   runs: {n_runs}   spectra: {total:,}")
print(f"single-run precision: {df['correct'].mean():.4f}\n")

print("agreement across runs (size of the largest identical group)\n")
summary = df.groupby("agreement").agg(
    spectra=("correct", "size"),
    coverage=("correct", lambda s: len(s) / total),
    precision=("correct", "mean"),
)
print(summary.round(4).to_string())

print("\nkeeping only spectra where at least k runs agree\n")
print(f"{'k':>3}{'coverage':>11}{'precision':>11}{'lift':>9}{'spectra':>12}")
baseline = df["correct"].mean()
for k in range(1, n_runs + 1):
    kept = df[df["agreement"] >= k]
    if not len(kept):
        continue
    print(f"{k:>3}{len(kept) / total:>11.4f}{kept['correct'].mean():>11.4f}"
          f"{kept['correct'].mean() - baseline:>+9.4f}{len(kept):>12,}")

print("\nunanimous versus not")
unanimous = df[df["agreement"] == n_runs]
divided = df[df["agreement"] < n_runs]
print(f"  all {n_runs} runs agree : {len(unanimous):>9,} spectra  precision {unanimous['correct'].mean():.4f}")
print(f"  runs disagree     : {len(divided):>9,} spectra  precision {divided['correct'].mean():.4f}")

# Would taking the majority answer beat taking any single run?
majority_correct = []
for row in df.itertuples(index=False):
    answers = [getattr(row, f"pred_{i}") for i in range(n_runs)]
    present = [a for a in answers if a]
    if not present:
        majority_correct.append(False)
        continue
    winner = Counter(present).most_common(1)[0][0]
    oks = [getattr(row, f"ok_{i}") for i in range(n_runs)]
    # A run that produced the winning sequence tells us whether that sequence is correct.
    majority_correct.append(next((ok for pred, ok in zip(answers, oks) if pred == winner), False))
df["majority_correct"] = majority_correct
print(f"\nsingle run          : {df['correct'].mean():.4f}")
print(f"majority vote of {n_runs}  : {df['majority_correct'].mean():.4f}  "
      f"({df['majority_correct'].mean() - df['correct'].mean():+.4f})")

gt = pd.read_csv(DATA / "gt_beam10.csv", usecols=["spectrum_id", "collection"])
merged = df.merge(gt, on="spectrum_id", how="left")
by_species = merged.groupby("collection").apply(
    lambda g: pd.Series({
        "unanimous_share": (g["agreement"] == n_runs).mean(),
        "precision_overall": g["correct"].mean(),
        "precision_if_unanimous": g.loc[g["agreement"] == n_runs, "correct"].mean(),
        "precision_if_divided": g.loc[g["agreement"] < n_runs, "correct"].mean(),
    }), include_groups=False)
print("\nunanimity by species")
print(by_species.sort_values("unanimous_share").round(4).to_string())
