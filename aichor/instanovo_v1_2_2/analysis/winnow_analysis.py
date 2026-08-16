"""What the Winnow scores are worth: ranking, per-species calibration, feature value.

Three questions:

* does the calibrated confidence *rank* better than the model's own log-probability?
  Calibration and ranking are different things, and ProteoBench's precision-coverage AUC
  is rank-based, so a miscalibrated score can still rank perfectly well;
* is the over-confidence uniform, or concentrated somewhere;
* which features carry the signal -- in particular whether the Koina-derived ones,
  which are what make this analysis expensive, earn their cost.

Usage: winnow_analysis.py <extract-dir>
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
N_SPECTRA = 779_879  # ProteoBench's coverage denominator: every benchmark spectrum

preds = pd.read_csv(DATA / "winnow_preds.csv")
logprobs = pd.read_csv(DATA / "logprobs_beam10.csv")


def prc_auc(scores, correct, n_spectra: int) -> float:
    """ProteoBench's precision-vs-coverage AUC (denovo_datapoint.get_prc_curve).

    One vertex per distinct score rather than per prediction: a threshold can never
    split a tied group, so only the point after a whole group is well defined.
    """
    s = np.asarray(scores, dtype=float)
    c = np.asarray(correct, dtype=bool)
    order = np.argsort(-s)
    s, c = s[order], c[order]
    rank = np.arange(1, len(s) + 1)
    precision = np.cumsum(c) / rank
    coverage = rank / n_spectra
    last_in_group = np.append(s[:-1] != s[1:], True)
    trapezoid = np.trapezoid if hasattr(np, "trapezoid") else np.trapz
    return float(trapezoid(precision[last_in_group], coverage[last_in_group]))


print("=== does recalibration improve the ranking? ===\n")
joined = preds.merge(logprobs, on="spectrum_id", how="inner").dropna(
    subset=["calibrated_confidence", "log_probs", "correct"])
print(f"rows compared: {len(joined):,}  (correct: {joined['correct'].mean():.4f})")
auc_calibrated = prc_auc(joined["calibrated_confidence"], joined["correct"], N_SPECTRA)
auc_logprob = prc_auc(joined["log_probs"], joined["correct"], N_SPECTRA)
print(f"  AUC, Winnow calibrated_confidence : {auc_calibrated:.4f}")
print(f"  AUC, InstaNovo log_probs          : {auc_logprob:.4f}")
print(f"  difference                        : {auc_calibrated - auc_logprob:+.4f}")
print(f"  Spearman between the two scores   : "
      f"{joined[['calibrated_confidence', 'log_probs']].corr(method='spearman').iloc[0, 1]:.4f}")
print("\nNote: `winnow predict` writes only the FDR-accepted rows, so both curves are")
print("truncated and the absolute values are not comparable to a full-coverage AUC. The")
print("subset is chosen by thresholding the calibrated score, which biases the comparison")
print("in its favour.")

print("\n=== calibration by species ===\n")
gt = pd.read_csv(DATA / "gt_beam10.csv", usecols=["spectrum_id", "collection"])
by_species = preds.copy()
# Winnow keys on "<experiment>:<scan>"; the scored table keys on the bare scan number.
by_species["scan"] = by_species["spectrum_id"].astype(str).str.rsplit(":", n=1).str[-1].astype(int)
by_species = by_species.merge(gt.rename(columns={"spectrum_id": "scan"}), on="scan", how="left")
calibration = by_species.groupby("collection").agg(
    n=("correct", "size"),
    empirical=("correct", "mean"),
    claimed=("calibrated_confidence", "mean"),
)
calibration["over_confidence"] = calibration["claimed"] - calibration["empirical"]
print(calibration.sort_values("over_confidence", ascending=False).round(4).to_string())
print("\nOver-confidence tracks difficulty: the worst-calibrated species are also the")
print("hardest ones, so the confidence is least trustworthy where it matters most.")

print("\n=== which features carry the signal ===\n")
features = pd.read_csv(DATA / "winnow_features.csv")
labelled = features.merge(preds, on="spectrum_id", how="inner")
target = labelled["correct"].astype(bool)


def single_feature_auc(values: pd.Series, correct: pd.Series) -> float:
    """Rank AUC of one feature against correctness. 0.5 is useless; below 0.5 is inverse."""
    usable = values.notna()
    values, correct = values[usable], correct[usable]
    if values.nunique() < 2:
        return float("nan")
    ranks = values.rank()
    n_pos, n_neg = correct.sum(), (~correct).sum()
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    return (ranks[correct].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)


scored = pd.DataFrame([
    {"feature": column, "auc": single_feature_auc(labelled[column], target)}
    for column in labelled.columns if column not in ("spectrum_id", "correct")
]).dropna()
scored["discrimination"] = (scored["auc"] - 0.5).abs()
print(scored.sort_values("discrimination", ascending=False)[["feature", "auc"]].round(4).to_string(index=False))
print("\nMeasured on the FDR-accepted subset, so the restricted range suppresses the")
print("absolute values; the ordering is the informative part.")
