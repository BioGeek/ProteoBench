"""Compare the seven inference modes against each other and against the spectra.

Four questions, all answered from the extracted per-spectrum outcomes:

* how each mode performs per species, and where refinement helps or hurts;
* how much the modes complement each other, and what each uniquely solves;
* what distinguishes a spectrum nothing solves from one everything solves;
* whether the mammalian refinement penalty tracks a property of the spectra.

Per-mode precisions are printed first as a check: they should reproduce the values
ProteoBench published for these runs.

Usage: mode_comparison.py <extract-dir>
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

DATA = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
MODES = ["greedy", "greedy_refined", "diffusion_only", "beam10",
         "beam10_refined", "knapsack_beam10", "knapsack_beam10_refined"]
MAMMALS = {"H.-sapiens", "Mus-musculus"}

# ProteoBench counts a peptide correct at "mass" level when the match is exact or mass-equivalent.
CORRECT_TYPES = ["exact", "mass"]

gt = pd.read_csv(DATA / "gt_beam10.csv")
outcome = pd.DataFrame({"spectrum_id": gt["spectrum_id"], "collection": gt["collection"]})
outcome["beam10"] = gt["match_type"].isin(CORRECT_TYPES).values
for mode in MODES:
    if mode == "beam10":
        continue
    frame = pd.read_csv(DATA / f"mode_{mode}.csv", usecols=["spectrum_id", "match_type"])
    outcome[mode] = frame["match_type"].isin(CORRECT_TYPES).values

print("per-mode peptide/mass precision (should match the published table)")
for mode in MODES:
    print(f"  {mode:26}{outcome[mode].mean():.4f}")

print("\n=== by species ===\n")
per_species = outcome.groupby("collection")[MODES].mean()
per_species.insert(0, "n", outcome.groupby("collection").size())
per_species["refine_gain"] = per_species["beam10_refined"] - per_species["beam10"]
per_species["diffusion_vs_beam"] = per_species["diffusion_only"] - per_species["beam10"]
print(per_species.sort_values("n", ascending=False).round(4).to_string())
print("\nRefinement helps every species except the two mammals; diffusion-only is close to")
print("beam search everywhere except the mammals, where it falls away sharply.")

print("\n=== complementarity ===\n")
any_correct = outcome[MODES].any(axis=1)
best_single = outcome[MODES].mean().max()
print(f"union of all seven (oracle ensemble) : {any_correct.mean():.4f}")
print(f"best single mode                     : {best_single:.4f}")
print(f"ensemble headroom                    : {any_correct.mean() - best_single:+.4f}")
print(f"all seven correct                    : {outcome[MODES].all(axis=1).mean():.4f}")
print(f"none correct                         : {(~any_correct).mean():.4f}  ({(~any_correct).sum():,})")
print("\nspectra only one mode solves:")
for mode in MODES:
    others = [m for m in MODES if m != mode]
    only = outcome[mode] & ~outcome[others].any(axis=1)
    print(f"  {mode:26}{only.sum():>8,}  ({only.mean():.3%})")

features = pd.read_csv(DATA / "spectrum_features.csv")
merged = outcome.merge(features, on="spectrum_id", how="left")
merged["n_correct"] = outcome[MODES].sum(axis=1)

print("\n=== what makes a spectrum hard ===\n")
grouped = merged.groupby("n_correct").agg(
    n=("spectrum_id", "size"),
    peptide_length=("peptide_length", "mean"),
    missing_frag_pct=("missing_frag_pct", "mean"),
    explained_all=("explained_all_pct", "mean"),
    cos_of_label=("cos", "mean"),
)
print(grouped.round(3).to_string())
print("\nThe label's own MS2PIP cosine falls with difficulty, so much of the hard tail is")
print("spectra without enough fragment evidence to determine any answer.")

print("\nunsolved rate by species:")
unsolved = merged.groupby("collection").agg(n=("spectrum_id", "size"),
                                            unsolved=("n_correct", lambda s: (s == 0).mean()))
print(unsolved.sort_values("unsolved", ascending=False).round(4).to_string())

print("\n=== mammalian versus non-mammalian spectra ===\n")
merged["mammal"] = merged["collection"].isin(MAMMALS)
cols = ["peptide_length", "missing_frag_pct", "explained_all_pct", "cos", "spec_pearson"]
summary = merged.groupby("mammal")[cols].mean()
summary.index = ["non-mammal", "mammal"]
print(summary.round(3).to_string())

ptm_cols = ["M-Oxidation", "Q-Deamidation", "N-Deamidation",
            "N-term Acetylation", "N-term Carbamylation", "N-term Ammonia-loss"]
ptm = merged.groupby("mammal")[ptm_cols].mean().mul(100)
ptm.index = ["non-mammal", "mammal"]
print("\nmodification incidence in the label (%):")
print(ptm.round(2).to_string())

print("\n=== refinement gain by peptide length ===\n")
merged["length_bin"] = pd.cut(merged["peptide_length"], [0, 10, 15, 20, 25, 1000],
                              labels=["<=10", "11-15", "16-20", "21-25", ">25"])
gain = (merged.groupby(["mammal", "length_bin"], observed=True)
        .apply(lambda g: g["beam10_refined"].mean() - g["beam10"].mean(), include_groups=False)
        .rename("gain").reset_index())
gain["mammal"] = gain["mammal"].map({True: "mammal", False: "non-mammal"})
print(gain.pivot(index="length_bin", columns="mammal", values="gain").round(4).to_string())
print("\nMonotone in both directions: refinement helps more on longer non-mammalian peptides")
print("and hurts more on longer mammalian ones.")
