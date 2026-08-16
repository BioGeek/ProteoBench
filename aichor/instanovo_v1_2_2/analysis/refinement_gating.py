"""Should InstaNovo+ refinement be applied to every spectrum, or only to some?

Refinement helps overall (0.7278 to 0.7317) but hurts mammals and hurts long, poorly
fragmented peptides. This evaluates gating rules that decide per spectrum whether to keep
the transformer's answer or the refined one.

No new inference is needed: both outcomes are already known for every spectrum, so a rule
is evaluated by choosing which of the two to take and scoring the result.

The distinction that decides whether a rule is real:

* a rule may only use information available **at inference time** -- the predicted
  peptide, the spectrum, and what the operator already knows (such as which organism was
  sampled);
* rules using ground-truth-derived quantities are reported too, clearly marked, because
  they bound what any rule built on that quantity could achieve. They are not deployable.

Usage: refinement_gating.py <extract-dir>
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
MAMMALS = {"H.-sapiens", "Mus-musculus"}
CORRECT = ["exact", "mass"]

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
refined = aligned(pd.read_csv(DATA / "mode_beam10_refined.csv", usecols=["spectrum_id", "match_type"]),
                  gt["spectrum_id"], "mode_beam10_refined.csv")
predicted = aligned(pd.read_csv(DATA / "mode_beam10.csv"), gt["spectrum_id"], "mode_beam10.csv")

df = pd.DataFrame({
    "spectrum_id": gt["spectrum_id"],
    "collection": gt["collection"],
    "base_ok": gt["match_type"].isin(CORRECT).values,
    "refined_ok": refined["match_type"].isin(CORRECT).values,
})

# Length of the peptide the model actually predicted -- known at inference, unlike the
# ground-truth length carried in the spectrum features.
def predicted_length(sequence: object) -> int:
    if not isinstance(sequence, str):
        return 0
    return len(re.sub(r"\[UNIMOD:\d+\]|-", "", sequence))


df["pred_len"] = predicted["peptidoform"].map(predicted_length).values
df["mammal"] = df["collection"].isin(MAMMALS)

features = pd.read_csv(DATA / "spectrum_features.csv",
                       usecols=["spectrum_id", "missing_frag_pct", "peptide_length"])
df = df.merge(features, on="spectrum_id", how="left")

n = len(df)
base = df["base_ok"].mean()
always = df["refined_ok"].mean()


def evaluate(name: str, refine_when: pd.Series, deployable: bool = True) -> dict:
    """Precision when refinement is applied only where `refine_when` holds."""
    chosen = np.where(refine_when, df["refined_ok"], df["base_ok"])
    precision = chosen.mean()
    return {
        "rule": name,
        "refined_share": float(refine_when.mean()),
        "precision": float(precision),
        "vs_always": float(precision - always),
        "vs_never": float(precision - base),
        "deployable": deployable,
    }


rows = [
    {"rule": "never refine (beam search alone)", "refined_share": 0.0, "precision": base,
     "vs_always": base - always, "vs_never": 0.0, "deployable": True},
    {"rule": "always refine (what was submitted)", "refined_share": 1.0, "precision": always,
     "vs_always": 0.0, "vs_never": always - base, "deployable": True},
]

# Deployable rules.
rows.append(evaluate("skip refinement on mammals", ~df["mammal"]))
for limit in (15, 20, 25):
    rows.append(evaluate(f"refine only if predicted length <= {limit}", df["pred_len"] <= limit))
rows.append(evaluate("skip on mammals, and only if predicted length <= 20",
                     (~df["mammal"]) & (df["pred_len"] <= 20)))

# The model's own uncertainty about its unrefined answer. Refinement has the most room
# where the transformer was least sure, and the log-probability is available at inference.
logprobs = pd.read_csv(DATA / "logprobs_beam10.csv")
if "scan_number" in logprobs.columns:
    logprobs = logprobs.rename(columns={"scan_number": "spectrum_id"})[["spectrum_id", "log_probs"]]
else:
    logprobs["spectrum_id"] = logprobs["spectrum_id"].astype(str).str.rsplit(":", n=1).str[-1].astype(int)
df = df.merge(logprobs[["spectrum_id", "log_probs"]], on="spectrum_id", how="left")
for quantile in (0.25, 0.5, 0.75):
    cutoff = df["log_probs"].quantile(quantile)
    rows.append(evaluate(
        f"refine only the least confident {int(quantile * 100)}% (log prob < {cutoff:.2f})",
        df["log_probs"] < cutoff))
rows.append(evaluate("skip mammals, and refine only the least confident 50%",
                     (~df["mammal"]) & (df["log_probs"] < df["log_probs"].quantile(0.5))))

# Upper bounds. These read the ground truth and cannot be deployed; they say how much
# room a rule built on the same quantity would have.
for limit in (10, 15):
    rows.append(evaluate(f"[bound] refine only if missing fragmentation < {limit}%",
                         df["missing_frag_pct"] < limit, deployable=False))
rows.append(evaluate("[bound] refine only where it actually helps (oracle gate)",
                     df["refined_ok"] & ~df["base_ok"], deployable=False))

table = pd.DataFrame(rows)
print(f"spectra: {n:,}\n")
print("peptide/mass precision under each gating rule\n")
print(table.assign(
    refined_share=lambda t: (t["refined_share"] * 100).round(1),
    precision=lambda t: t["precision"].round(4),
    vs_always=lambda t: t["vs_always"].round(4),
    vs_never=lambda t: t["vs_never"].round(4),
).to_string(index=False))

print("\n'refined_share' is the percentage of spectra sent through refinement, which is")
print("also the compute saved: refinement is roughly half the cost of the run.")

best = table[table["deployable"]].sort_values("precision", ascending=False).iloc[0]
print(f"\nbest deployable rule: {best['rule']}")
print(f"  precision {best['precision']:.4f} against {always:.4f} for always-refine "
      f"({best['vs_always']:+.4f})")
print(f"  and {base:.4f} for never-refine ({best['vs_never']:+.4f})")
print(f"  refining {best['refined_share'] * 100:.1f}% of spectra")

oracle = table[table["rule"].str.contains("oracle")].iloc[0]
captured = (best["precision"] - always) / (oracle["precision"] - always) if oracle["precision"] > always else float("nan")
print(f"\noracle gate reaches {oracle['precision']:.4f}; the best deployable rule captures "
      f"{captured:.1%} of the gap between always-refine and that bound.")
