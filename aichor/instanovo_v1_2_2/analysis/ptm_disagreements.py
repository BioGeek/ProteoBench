"""Where every mode agrees on the same peptide as the label, but modifies it differently.

Looking for labels that may be wrong, and for modifications the original database search
never looked for. The filter that makes the result interpretable is the last one: the
predicted peptide must have an *identical backbone* to the label, so the only disagreement
is the modification state. Without it the survivors are mostly low-quality spectra paired
with wholly different sequences of coincidentally similar mass, which is not evidence of
anything.

The mass difference then separates the cases: zero means the same modification on a
different residue, a known modification mass means one the search may have missed.

Caveat worth keeping in mind when reading the output: the modes are *not* independent
decoders. They are the same two models under different search strategies, so agreement
reflects shared bias rather than independent corroboration.

Usage: ptm_disagreements.py <extract-dir>
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd

DATA = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
# All seven modes take part in the consensus. beam10's verdict lives in the ground-truth
# extract while its predicted peptide is in mode_beam10.csv, so it is assembled separately
# below rather than being merely required to be wrong.
MODES = ["greedy", "greedy_refined", "diffusion_only", "beam10_refined",
         "knapsack_beam10", "knapsack_beam10_refined"]

RESIDUE_MASS = {
    "G": 57.021464, "A": 71.037114, "S": 87.032028, "P": 97.052764, "V": 99.068414,
    "T": 101.047678, "C": 103.009185, "L": 113.084064, "I": 113.084064, "N": 114.042927,
    "D": 115.026943, "Q": 128.058578, "K": 128.094963, "E": 129.042593, "M": 131.040485,
    "H": 137.058912, "F": 147.068414, "R": 156.101111, "Y": 163.063329, "W": 186.079313,
}
UNIMOD_MASS = {1: 42.010565, 4: 57.021464, 5: 43.005814,
               7: 0.984016, 35: 15.994915, 385: -17.026549}
WATER = 18.010565
TOKEN = re.compile(r"([A-Z])(\[UNIMOD:(\d+)\])?|\[UNIMOD:(\d+)\]")

KNOWN_DELTAS = {
    "phospho": 79.96633, "acetyl": 42.010565, "carbamyl": 43.005814,
    "oxidation": 15.994915, "deamidation": 0.984016, "methyl": 14.015650,
    "dimethyl": 28.031300, "formyl": 27.994915, "carbamidomethyl": 57.021464,
    "ammonia-loss": -17.026549, "water-loss": -18.010565,
}


def peptide_mass(sequence: object):
    """Monoisotopic mass of a ProForma peptide, or None if a residue is unknown."""
    if not isinstance(sequence, str) or not sequence:
        return None
    total = WATER
    for match in TOKEN.finditer(sequence.replace("-", "")):
        residue, _, modification, standalone = match.groups()
        if residue:
            if residue not in RESIDUE_MASS:
                return None
            total += RESIDUE_MASS[residue]
            if modification:
                total += UNIMOD_MASS.get(int(modification), float("nan"))
        elif standalone:
            total += UNIMOD_MASS.get(int(standalone), float("nan"))
    return total


def backbone(sequence: object) -> str:
    """The bare residue sequence, with I and L equated (they are isobaric)."""
    return re.sub(r"\[UNIMOD:\d+\]", "", str(sequence)).replace("-", "").replace("I", "L")


def classify(delta: float, tolerance: float = 0.01) -> str:
    if abs(delta) < tolerance:
        return "same modification, different residue"
    for name, mass in KNOWN_DELTAS.items():
        if abs(delta - mass) < tolerance:
            return f"prediction adds {name}"
        if abs(delta + mass) < tolerance:
            return f"label carries {name}, prediction does not"
    return "other"


def aligned(frame, reference, name: str):
    """Return `frame` only if its rows line up with `reference`.

    Several analyses below assign columns positionally across separately-read files,
    which is only valid if every file carries the same spectra in the same order. The
    marginal precision checks cannot catch a violation -- a permutation leaves a mean
    unchanged -- so the assumption is asserted here rather than trusted.
    """
    if len(frame) != len(reference) or not frame["spectrum_id"].reset_index(drop=True).equals(
            reference.reset_index(drop=True)):
        raise SystemExit(f"{name} is not row-aligned with the reference; a keyed merge is needed")
    return frame


gt = pd.read_csv(DATA / "gt_beam10.csv")
df = pd.DataFrame({
    "spectrum_id": gt["spectrum_id"],
    "truth": gt["peptidoform_ground_truth"],
    "collection": gt["collection"],
    "beam10_match": gt["match_type"],
})
for mode in MODES:
    frame = aligned(pd.read_csv(DATA / f"mode_{mode}.csv",
                                usecols=["spectrum_id", "match_type", "peptidoform"]),
                    gt["spectrum_id"], f"mode_{mode}.csv")
    df[f"{mode}_pred"] = frame["peptidoform"].values
    df[f"{mode}_ok"] = frame["match_type"].isin(["exact", "mass"]).values

beam10 = aligned(pd.read_csv(DATA / "mode_beam10.csv"), gt["spectrum_id"], "mode_beam10.csv")
df["beam10_pred"] = beam10["peptidoform"].values
df["beam10_ok"] = gt["match_type"].isin(["exact", "mass"]).values
ALL_MODES = MODES + ["beam10"]

every_mode_wrong = ~df[[f"{m}_ok" for m in ALL_MODES]].any(axis=1)
df = df[every_mode_wrong]
print(f"spectra where every mode is wrong: {len(df):,}")

prediction_columns = [f"{m}_pred" for m in ALL_MODES]
normalised = df[prediction_columns].apply(
    lambda column: column.astype(str).str.replace("-", "", regex=False))
unanimous = normalised.nunique(axis=1) == 1
df = df[unanimous].copy()
df["agreed"] = normalised.loc[unanimous.index[unanimous], prediction_columns[0]]
print(f"...and all seven agree on the same peptide: {len(df):,}")

same_backbone = [backbone(t) == backbone(a) for t, a in zip(df["truth"], df["agreed"])]
df = df[same_backbone].copy()
print(f"...with an identical backbone, differing only in modifications: {len(df):,}\n")

deltas = []
for agreed, truth in zip(df["agreed"], df["truth"]):
    mass_a, mass_t = peptide_mass(agreed), peptide_mass(truth)
    deltas.append(mass_a - mass_t if (mass_a is not None and mass_t is not None) else float("nan"))
df["delta"] = deltas
df = df.dropna(subset=["delta"])
df["explanation"] = df["delta"].map(classify)

print("mass delta (prediction minus label):")
print(df["delta"].round(4).value_counts().head(12).to_string())
print("\nclassification:")
print(df["explanation"].value_counts().to_string())
print("\nby species:")
print(df["collection"].value_counts().to_string())
print("\nexamples:")
print(df[["collection", "truth", "agreed", "delta"]].head(10).to_string(index=False, max_colwidth=44))

df.to_csv(DATA / "ptm_disagreements.csv", index=False)
print(f"\nwrote {DATA / 'ptm_disagreements.csv'} ({len(df):,} rows)")
print("\nThe zero-delta group is the notable one: the peptide and the modification are both")
print("right and only the site differs, yet ProteoBench scores these as complete misses.")
