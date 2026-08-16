"""Is the bottleneck the search, or the model's candidate set?

The oracle ceiling says the label is somewhere in the ten beams far more often than it is
ranked first. That has two very different explanations, and they call for different work:

* **misranked** -- the label is in the beam but not at the top, so better ranking or a
  wider beam could recover it;
* **absent** -- the model never proposes the label at all, so no amount of reranking helps
  and the ceiling is a property of the model, not the search.

This splits every spectrum into top-1 correct / present but misranked / absent, and
stratifies the split so the answer can be read per species, per length and per spectrum
quality. It also reports the cumulative oracle at each rank, whose shape says whether a
wider beam would still be gaining candidates at rank 10 or has flattened.

Usage: beam_failure.py <extract-dir> <predictions-csv-or-stdin>
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path(sys.argv[1])
PREDICTIONS = Path(sys.argv[2])
N_BEAMS = 10


def normalise(sequence: object) -> str:
    return sequence.replace("-", "").strip() if isinstance(sequence, str) else ""


def il(sequence: str) -> str:
    return sequence.replace("I", "L")


gt = pd.read_csv(DATA / "gt_beam10.csv")
truth = {sid: normalise(seq) for sid, seq in
         zip(gt["spectrum_id"], gt["peptidoform_ground_truth"])}
print(f"[beam_failure] ground truth for {len(truth):,} spectra", flush=True)

beam_columns = [f"predictions_beam_{k}" for k in range(N_BEAMS)]
records = []
for chunk in pd.read_csv(PREDICTIONS, usecols=["scan_number"] + beam_columns,
                         chunksize=100_000, low_memory=False):
    for row in chunk.itertuples(index=False):
        label = truth.get(row.scan_number)
        if label is None:
            continue
        label_il = il(label)
        first_exact = first_il = -1
        for k in range(N_BEAMS):
            candidate = normalise(getattr(row, f"predictions_beam_{k}"))
            if not candidate:
                continue
            if first_exact < 0 and candidate == label:
                first_exact = k
            if first_il < 0 and il(candidate) == label_il:
                first_il = k
            if first_exact >= 0 and first_il >= 0:
                break
        records.append((row.scan_number, first_exact, first_il))

ranks = pd.DataFrame(records, columns=["spectrum_id", "first_exact", "first_il"])
df = ranks.merge(gt[["spectrum_id", "collection"]], on="spectrum_id", how="left")
features = pd.read_csv(DATA / "spectrum_features.csv",
                       usecols=["spectrum_id", "peptide_length", "missing_frag_pct", "cos"])
df = df.merge(features, on="spectrum_id", how="left")
total = len(df)


def outcome(first: pd.Series) -> pd.Series:
    return pd.cut(first, [-2, -1, 0, N_BEAMS], labels=["absent", "top-1", "misranked"])


for level, column in (("exact", "first_exact"), ("exact+IL", "first_il")):
    df[f"outcome_{level}"] = outcome(df[column])
    counts = df[f"outcome_{level}"].value_counts(normalize=True)
    print(f"\n=== {level} ===")
    for name in ("top-1", "misranked", "absent"):
        print(f"  {name:12}{counts.get(name, 0):.4f}")

print("\ncumulative oracle at rank k (exact / exact+IL)\n")
print(f"{'k':>3}{'exact':>10}{'exact+IL':>11}{'exact gain':>12}")
previous_exact = 0.0
for k in range(N_BEAMS):
    cumulative_exact = ((df["first_exact"] >= 0) & (df["first_exact"] <= k)).mean()
    cumulative_il = ((df["first_il"] >= 0) & (df["first_il"] <= k)).mean()
    print(f"{k:>3}{cumulative_exact:>10.4f}{cumulative_il:>11.4f}{cumulative_exact - previous_exact:>+12.4f}")
    previous_exact = cumulative_exact
print("\nA gain still large at k=9 would argue for a wider beam; one that has flattened")
print("means the candidate set, not the search width, is the limit.")

print("\n=== where the label is absent from the beam entirely (exact+IL) ===\n")
df["absent_il"] = df["first_il"] < 0
by_species = df.groupby("collection").agg(n=("spectrum_id", "size"), absent=("absent_il", "mean"))
print(by_species.sort_values("absent", ascending=False).round(4).to_string())

df["length_bin"] = pd.cut(df["peptide_length"], [0, 10, 15, 20, 25, 1000],
                          labels=["<=10", "11-15", "16-20", "21-25", ">25"])
print("\nby peptide length:")
print(df.groupby("length_bin", observed=True).agg(
    n=("spectrum_id", "size"),
    absent=("absent_il", "mean"),
    misranked=("outcome_exact+IL", lambda s: (s == "misranked").mean()),
).round(4).to_string())

print("\nby how well the label explains its spectrum (MS2PIP cosine):")
df["cos_bin"] = pd.cut(df["cos"], [0, 0.5, 0.7, 0.85, 0.95, 1.0])
print(df.groupby("cos_bin", observed=True).agg(
    n=("spectrum_id", "size"),
    absent=("absent_il", "mean"),
    misranked=("outcome_exact+IL", lambda s: (s == "misranked").mean()),
).round(4).to_string())

misranked = df[(df["first_il"] > 0)]
print(f"\nof the {len(misranked):,} spectra whose label is in the beam but not first,")
print("the rank it actually occupies:")
print(misranked["first_il"].value_counts().sort_index().to_string())
