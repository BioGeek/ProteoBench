"""What kind of wrong answers does each mode give, and does refinement's penalty survive matching?

Two questions:

* **Error provenance.** When a mode is wrong, is the answer still a real peptide of that
  species, or something that exists nowhere? A near-neighbour of a real protein is a very
  different failure from an invention, and interventions can trade one for the other
  without moving the headline accuracy.

* **Confounding.** "Refinement hurts mammals" compares groups that differ in more than
  taxonomy. Mammalian spectra have twice the missing fragmentation. Comparing within
  matched strata of length, fragmentation and modification state shows whether the penalty
  survives, or whether it was composition all along.

Usage: error_provenance.py <extract-dir>
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
MODES = ["greedy", "greedy_refined", "diffusion_only", "beam10",
         "beam10_refined", "knapsack_beam10", "knapsack_beam10_refined"]
MAMMALS = {"H.-sapiens", "Mus-musculus"}
CORRECT = ["exact", "mass"]

gt = pd.read_csv(DATA / "gt_beam10.csv")
frames = {"beam10": gt[["spectrum_id", "match_type", "category"]]}
for mode in MODES:
    if mode == "beam10":
        continue
    frames[mode] = pd.read_csv(DATA / f"mode_{mode}.csv",
                               usecols=["spectrum_id", "match_type", "category"])

print("=== when a mode is wrong, is its answer a real peptide of that species? ===\n")
print(f"{'mode':26}{'wrong':>10}{'in FASTA':>11}{'not in FASTA':>14}{'share in FASTA':>16}")
for mode in MODES:
    frame = frames[mode]
    wrong = ~frame["match_type"].isin(CORRECT)
    in_fasta = (frame.loc[wrong, "category"] == "in_fasta").sum()
    not_in = (frame.loc[wrong, "category"] == "not_in_fasta").sum()
    print(f"{mode:26}{wrong.sum():>10,}{in_fasta:>11,}{not_in:>14,}"
          f"{in_fasta / max(wrong.sum(), 1):>16.4f}")
print("\nA higher share in FASTA means the mode's mistakes are plausible peptides rather")
print("than inventions. Being in the FASTA is a property of the reference database, not")
print("evidence the peptide was present in the sample.")

# --- does the mammalian refinement penalty survive matching? ------------------------

features = pd.read_csv(DATA / "spectrum_features.csv",
                       usecols=["spectrum_id", "peptide_length", "missing_frag_pct",
                                "M-Oxidation", "N-Deamidation", "Q-Deamidation"])
df = pd.DataFrame({
    "spectrum_id": gt["spectrum_id"],
    "collection": gt["collection"],
    "base_ok": gt["match_type"].isin(CORRECT).values,
    "refined_ok": frames["beam10_refined"]["match_type"].isin(CORRECT).values,
}).merge(features, on="spectrum_id", how="left")
df["mammal"] = df["collection"].isin(MAMMALS)
df["gain"] = df["refined_ok"].astype(int) - df["base_ok"].astype(int)
df["modified"] = df[["M-Oxidation", "N-Deamidation", "Q-Deamidation"]].any(axis=1)
df["length_bin"] = pd.cut(df["peptide_length"], [0, 10, 15, 20, 25, 1000],
                          labels=["<=10", "11-15", "16-20", "21-25", ">25"])
df["frag_bin"] = pd.cut(df["missing_frag_pct"], [-0.01, 5, 15, 30, 101],
                        labels=["0-5%", "5-15%", "15-30%", ">30%"])

crude = df.groupby("mammal")["gain"].mean()
print("\n=== refinement gain, crude ===")
print(f"  non-mammal {crude[False]:+.4f}")
print(f"  mammal     {crude[True]:+.4f}")
print(f"  difference {crude[True] - crude[False]:+.4f}")

# Standardise to the non-mammalian stratum distribution, so the comparison holds the
# spectrum mix fixed and only the taxonomy varies.
strata = ["length_bin", "frag_bin", "modified"]
cell_gain = df.groupby(strata + ["mammal"], observed=True)["gain"].agg(["mean", "size"]).reset_index()
weights = (df[~df["mammal"]].groupby(strata, observed=True).size()
           .rename("weight").reset_index())
weights["weight"] /= weights["weight"].sum()
merged = cell_gain.merge(weights, on=strata, how="inner")

print("\n=== refinement gain, standardised to the non-mammalian spectrum mix ===")
for is_mammal in (False, True):
    side = merged[merged["mammal"] == is_mammal]
    standardised = np.average(side["mean"], weights=side["weight"])
    label = "mammal" if is_mammal else "non-mammal"
    print(f"  {label:11}{standardised:+.4f}   (strata covered: {len(side)})")
mammal_side = merged[merged["mammal"]]
other_side = merged[~merged["mammal"]]
difference = (np.average(mammal_side["mean"], weights=mammal_side["weight"])
              - np.average(other_side["mean"], weights=other_side["weight"]))
print(f"  difference {difference:+.4f}")
print("\nIf the standardised difference stays close to the crude one, the penalty is not")
print("explained by mammals simply having harder or differently composed spectra.")

# Bootstrap the standardised difference over spectra.
rng = np.random.default_rng(0)
estimates = []
for _ in range(200):
    sample = df.sample(len(df), replace=True, random_state=int(rng.integers(1 << 31)))
    cells = sample.groupby(strata + ["mammal"], observed=True)["gain"].mean().reset_index()
    joined = cells.merge(weights, on=strata, how="inner")
    m, o = joined[joined["mammal"]], joined[~joined["mammal"]]
    if len(m) and len(o):
        estimates.append(np.average(m["gain"], weights=m["weight"])
                         - np.average(o["gain"], weights=o["weight"]))
low, high = np.percentile(estimates, [2.5, 97.5])
print(f"\n95% bootstrap interval for the standardised difference: [{low:+.4f}, {high:+.4f}]")
