"""Score InstaNovo internal held-out predictions with ProteoBench's de novo scorer.

The internal evaluation harness reports `aa_prec`, `aa_recall` and `pep_recall` per dataset.
ProteoBench reports something different: an exact/mass split, three ambiguity toggles on top
of exact matching (I/L, deamidation, both) and an area under the precision-vs-coverage curve.
None of those are recoverable from the internal numbers, so a claim like "the ProteoBench
conclusions transfer to our test sets" cannot be checked against the harness output as it
stands. This adapter closes that gap: it takes the per-dataset prediction CSVs a run writes
to `${output_dir}/${run_name}/samples/*.csv` and pushes them through the same
`DenovoScores` / `DenovoDatapoint` code path a ProteoBench submission goes through.

**Column mapping is deliberately identical to ProteoBench's own InstaNovo parser**
(`io_parse_settings/denovo/DDA/HCD/parse_settings_instanovo.toml`), because the whole point is
comparability:

    predictions      -> sequence -> proforma -> peptidoform
    log_probs        -> score
    token_log_probs  -> aa_scores

Note that `score` is the *log* probability, not the `confidence` column, and that per-token
scores are kept as raw log probabilities. Both are what the TOML specifies. Neither choice
affects AUC (the curve is rank-based and both transforms are monotone), but using `confidence`
would silently change the tie structure, and ties are what the curve's vertices are built from.

Two departures from the ProteoBench parser, both forced by the data:

* **Spectrum IDs are left alone.** ProteoBench's `spectrum_id_mapper` extracts trailing digits
  into an integer scan ID, which is unique within its single benchmark file. Internal IDs look
  like `Peng2021_Herceptin_elastase:4135` and the trailing number is only unique *within* a
  dataset, so they are kept as strings and prefixed with the dataset name.
* **No FASTA category.** `DenovoScores.add_fasta_category` matches wrong answers against
  per-species peptide sets downloaded from the ProteoBench server. Those sets describe the
  ProteoBench benchmark's species, not ours, so the lookup is skipped (see `_ScoresNoFasta`).
  The `category` column is still emitted, and still marks correct predictions, but "in_fasta"
  will never be assigned.

Two quirks of ProteoBench's scorer that this adapter reproduces faithfully, and which will
look like adapter bugs if you meet them cold:

* **Amino-acid `exact` can exceed amino-acid `mass`.** At residue level, `aa_exact_dn` is
  positional character equality, computed without any mass alignment, while `aa_matches_dn`
  is the mass-based prefix/suffix match. A badly wrong prediction still collects exact credit
  wherever a character coincides by chance -- a reversed peptide scores 1/13 exact and 0/13
  mass -- so on datasets with many wrong answers the exact rate sits *above* the mass rate,
  inverting the ordering that holds at peptide level.
* **Amino-acid `coverage` can exceed 1.0.** Its denominator counts ground-truth residues and
  its numerator counts predicted ones, so a mode that predicts peptides longer than the labels
  reports coverage above 1.

A caveat worth carrying into any comparison of refined runs: InstaNovo+ 1.2.2 declares but
never fills its per-token score column. When no per-token scores survive, ProteoBench
broadcasts the peptide score across every residue, which turns amino-acid ranking into peptide
ranking and inflates amino-acid AUC relative to a mode that reports genuine per-residue
scores. This script reproduces that behaviour (it has to, for parity) and flags it per dataset
in the `aa_scores_broadcast` column of the metrics table, so an inflated aa AUC is at least
visible rather than silent.

Usage
-----
    score_with_proteobench.py <samples-dir> --out <out-dir> [--label greedy_v1_3]

`<samples-dir>` is a directory of `<dataset>.csv` files, i.e. a local copy of a run's
`samples/` prefix. Download one with:

    aichor storage cloud download \\
        --storage-id dtu-denovo-s-2e6da747d6d34f62-outputs \\
        --remote-path evaluation/<run_name>/samples/ --local-path <samples-dir>

Outputs `metrics.csv` (long format, one row per dataset x level x evaluation x ambiguity,
plus a pooled `__ALL__` dataset) and, with `--save-intermediate`, one parquet per dataset
holding the per-spectrum match columns that `paired_stats.py` and the other analysis scripts
consume.
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from psm_utils import Peptidoform
from pyteomics.mass import std_aa_mass as _STD_AA_MASS

from proteobench.datapoint.denovo_datapoint import (
    calculate_auc,
    calculate_prc,
    collapse_aa_scores,
    get_prc_curve,
)
from proteobench.score.denovoscores import AMBIGUITY_COMBOS, DenovoScores, get_ambiguity_suffix

# Accepted spellings for each field. The first match wins. The internal pipeline writes the
# first entry of each list; the rest cover the refinement and diffusion writers, whose column
# names differ, and are taken from the same fallback chain used by the ProteoBench sweep
# (aichor/instanovo_v1_2_2/run_sweep.py).
PREDICTION_COLUMNS = ["predictions", "prediction", "preds"]
TARGET_COLUMNS = ["targets", "target", "modified_sequence"]
SCORE_COLUMNS = ["log_probs", "prediction_log_probability", "log_probability"]
# `instanovo_prediction_token_log_probabilities` is deliberately absent: in a refinement run
# `predictions` holds the InstaNovo+ sequence, so pairing it with the *transformer's* per-token
# scores misaligns them wherever refinement changed the peptide, and collapse_aa_scores then
# dies on "All arrays must be of the same length".
TOKEN_SCORE_COLUMNS = [
    "token_log_probs",
    "prediction_token_log_probabilities",
    "instanovoplus_prediction_token_log_probabilities",
    "diffusion_token_log_probabilities",
]

LEVELS = ["peptide", "aa"]

# ProteoBench's `DenovoScores.AA_MASSES` covers only the 20 standard residues, and
# `get_token_mass` indexes it without a fallback -- so a single predicted selenocysteine
# raises `KeyError: 'U'` and takes the whole run's scoring down. That is not hypothetical:
# the v1.3 133-residue vocabulary includes U, and mass-constrained knapsack beam search emits
# it (the knapsack runs crashed here while the greedy runs did not).
#
# Taken from `pyteomics.mass.std_aa_mass` rather than computed here. pyteomics is already a
# ProteoBench dependency and its table covers 23 residues, agreeing with the hand-written
# AA_MASSES to within 1e-6 on every residue the two share -- so this adds the missing residues
# without introducing a second, divergent source of truth.
EXTRA_AA_MASSES = {
    residue: _STD_AA_MASS[residue]
    for residue in ("U", "O", "J")  # selenocysteine, pyrrolysine, leucine/isoleucine
    if residue in _STD_AA_MASS
}


class _ScoresNoFasta(DenovoScores):
    """`DenovoScores` with the species peptide-set lookup disabled and the residue table widened.

    Two deviations from the base class, both documented in the module docstring:

    * `load_species_sets` returns nothing. The base class downloads per-species peptide sets
      from the ProteoBench server to label wrong answers as "a real peptide of that species"
      vs "an invention". Those sets describe the ProteoBench benchmark, not our held-out data.
    * `AA_MASSES` gains selenocysteine and pyrrolysine. Scoring them correctly is strictly
      better than the alternatives available: upstream crashes, and treating the rows as
      unscoreable would penalise exactly the modes that emit them.
    """

    def __init__(self) -> None:
        super().__init__()
        self.AA_MASSES = {**self.AA_MASSES, **EXTRA_AA_MASSES}

    def load_species_sets(self, path: str | None = None) -> dict[str, set]:
        return {}


KNOWN_RESIDUES = set(DenovoScores().AA_MASSES) | set(EXTRA_AA_MASSES)


def _unknown_residues(peptidoform: Peptidoform | None) -> set[str]:
    """Residues this scorer has no mass for. Non-empty means the row cannot be scored."""
    if peptidoform is None:
        return set()
    return {aa for aa in peptidoform.sequence if aa not in KNOWN_RESIDUES}


def _pick_column(df: pd.DataFrame, candidates: list[str], what: str) -> str | None:
    for name in candidates:
        if name in df.columns:
            return name
    print(f"  [warn] no column for {what}; tried {candidates}", file=sys.stderr)
    return None


def _parse_token_scores(value: object) -> list[float] | None:
    """Parse a per-token score cell, which the writer emits as a string repr of a list."""
    if isinstance(value, list):
        return [float(v) for v in value]
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = ast.literal_eval(value)
    except (ValueError, SyntaxError):
        return None
    if not isinstance(parsed, (list, tuple)):
        return None
    return [float(v) for v in parsed]


def _to_peptidoform(sequence: object) -> Peptidoform | None:
    """Peptidoform or None. ProteoBench swallows failures here; we count them instead."""
    if not isinstance(sequence, str) or not sequence.strip():
        return None
    try:
        return Peptidoform(sequence)
    except Exception:
        return None


def build_standard_frame(csv_path: Path, dataset: str) -> tuple[pd.DataFrame, dict]:
    """Read one dataset's predictions into the frame `DenovoScores` expects.

    Returns the frame and a dict of provenance/diagnostics for the metrics table.
    """
    raw = pd.read_csv(csv_path, low_memory=False)

    prediction_column = _pick_column(raw, PREDICTION_COLUMNS, "predictions")
    target_column = _pick_column(raw, TARGET_COLUMNS, "ground truth")
    score_column = _pick_column(raw, SCORE_COLUMNS, "peptide score")
    if prediction_column is None or target_column is None or score_column is None:
        raise SystemExit(f"{csv_path} is missing a required column; columns are {list(raw.columns)}")

    token_column = None
    for name in TOKEN_SCORE_COLUMNS:
        if name in raw.columns and raw[name].notna().any():
            token_column = name
            break

    spectrum_ids = raw["spectrum_id"] if "spectrum_id" in raw.columns else raw.index.astype(str)
    frame = pd.DataFrame(
        {
            "spectrum_id": dataset + "/" + spectrum_ids.astype(str),
            "collection": dataset,
            "score": pd.to_numeric(raw[score_column], errors="coerce"),
        }
    )
    frame["peptidoform"] = raw[prediction_column].map(_to_peptidoform)
    frame["peptidoform_ground_truth"] = raw[target_column].map(_to_peptidoform)

    # Rows whose *ground truth* will not parse cannot be scored at all -- they are not a
    # prediction failure, they are an unusable label, and leaving them in would silently
    # depress every metric. Drop them, loudly.
    # Any residue still outside the (widened) mass table would raise a bare KeyError deep
    # inside get_token_mass and lose the whole run, so screen for it here instead. Predictions
    # are demoted to a miss; labels make the row unscoreable. Both are counted and reported
    # rather than silently dropped -- a rising count means the vocabulary has moved again.
    unknown_in_prediction = frame["peptidoform"].map(_unknown_residues)
    unknown_in_label = frame["peptidoform_ground_truth"].map(_unknown_residues)
    offending = sorted(set().union(*unknown_in_prediction, *unknown_in_label)) if len(frame) else []
    if offending:
        n_pred = int(unknown_in_prediction.map(bool).sum())
        n_label = int(unknown_in_label.map(bool).sum())
        print(
            f"  [warn] residues with no mass in this scorer: {offending} "
            f"({n_pred:,} predictions demoted to misses, {n_label:,} labels unscoreable)",
            file=sys.stderr,
        )
        frame.loc[unknown_in_prediction.map(bool), "peptidoform"] = None
        frame.loc[unknown_in_label.map(bool), "peptidoform_ground_truth"] = None

    usable = frame["peptidoform_ground_truth"].notna()
    unusable_labels = int((~usable).sum())
    if unusable_labels:
        print(f"  [warn] {unusable_labels:,} rows have an unparseable ground truth; dropped", file=sys.stderr)
        # Both frames must be filtered by the same mask and reindexed together: the per-token
        # scores below are read from `raw` and zipped positionally against `frame`.
        frame = frame[usable].reset_index(drop=True)
        raw = raw[usable.to_numpy()].reset_index(drop=True)

    # Unparseable *predictions* are kept as None. ProteoBench does the same (it drops them
    # before merging against ground truth, so they survive the left join as NaN), and it
    # matters: they still count towards the denominator, showing up as coverage below 1.0
    # rather than vanishing from the benchmark.
    unparseable = int(frame["peptidoform"].isna().sum())

    # Per-residue scores, aligned to the emitted prediction.
    broadcast = True
    if token_column is not None:
        parsed = raw[token_column].map(_parse_token_scores)
        lengths_ok = [
            scores is not None and pep is not None and len(scores) == _token_length(pep)
            for scores, pep in zip(parsed, frame["peptidoform"])
        ]
        if any(lengths_ok):
            broadcast = False
            frame["aa_scores"] = [
                scores if ok else _broadcast_scores(pep, score)
                for scores, ok, pep, score in zip(parsed, lengths_ok, frame["peptidoform"], frame["score"])
            ]
            mismatched = sum(1 for ok, pep in zip(lengths_ok, frame["peptidoform"]) if not ok and pep is not None)
            if mismatched:
                print(
                    f"  [warn] {mismatched:,} rows had per-token scores whose length did not match "
                    f"the emitted peptide; broadcast the peptide score for those rows instead",
                    file=sys.stderr,
                )
    if broadcast:
        # Mirrors ParseSettingsDeNovo: "If AA scores are not provided, simulate them from
        # peptide score". Inflates amino-acid AUC; flagged in the metrics table.
        frame["aa_scores"] = [_broadcast_scores(pep, score) for pep, score in zip(frame["peptidoform"], frame["score"])]

    diagnostics = {
        "n_rows": len(frame),
        "unusable_ground_truth": unusable_labels,
        "unparseable_prediction": unparseable,
        "score_column": score_column,
        "token_score_column": token_column if not broadcast else "",
        "aa_scores_broadcast": broadcast,
    }
    return frame, diagnostics


def _token_length(peptidoform: Peptidoform) -> int:
    """Number of scored tokens: one per residue, plus one if there is an N-terminal mod.

    Matches `ParseSettingsDeNovo.get_length_peptidoform_with_nterm` and, more importantly,
    `DenovoScores.convert_peptidoform`, which emits the N-terminal modification as its own
    token. `collapse_aa_scores` flattens `aa_scores` against those tokens, so a mismatch here
    surfaces as "All arrays must be of the same length" much later.
    """
    n_term = peptidoform.properties.get("n_term")
    return len(peptidoform.sequence) + (1 if n_term else 0)


def _broadcast_scores(peptidoform: Peptidoform | None, score: float) -> list[float]:
    if peptidoform is None:
        return []
    return [float(score)] * _token_length(peptidoform)


def score_arrays(
    df: pd.DataFrame, level: str, evaluation: str, allow_il: bool = False, allow_deamidation: bool = False
) -> tuple[np.ndarray, np.ndarray, int]:
    """The (scores, is_correct, n) extraction performed inside `DenovoDatapoint.get_metrics`.

    Factored out so per-dataset metrics and the pooled metrics are computed from identical
    logic -- pooling by re-deriving the arrays is the only way to get a genuine cross-dataset
    curve, since averaging per-dataset AUCs is not the AUC of the pooled ranking.
    """
    if evaluation == "mass":
        evaluation_list = ["mass", "exact"]
        match_column = "match_type"
        exact_dn_column = "aa_exact_dn"
    elif evaluation == "exact":
        evaluation_list = ["exact"]
        suffix = get_ambiguity_suffix(allow_il, allow_deamidation)
        match_column = f"match_type{suffix}"
        exact_dn_column = f"aa_exact_dn{suffix}"
    else:
        raise ValueError(f"evaluation must be 'exact' or 'mass', got {evaluation!r}")

    if level == "peptide":
        n = len(df)
        scored = df.dropna(subset="peptidoform")
        return (
            scored["score"].to_numpy(dtype=float),
            scored[match_column].isin(evaluation_list).to_numpy(dtype=bool),
            n,
        )

    n = int(df["aa_matches_gt"].apply(len).sum())
    scored = df.dropna(subset="peptidoform")
    flattened = collapse_aa_scores(scored, evaluation_type=evaluation, exact_dn_column=exact_dn_column)
    return (
        flattened["aa_score"].to_numpy(dtype=float),
        flattened["aa_match"].to_numpy(dtype=bool),
        n,
    )


def metrics_from_arrays(scores: np.ndarray, is_correct: np.ndarray, n: int) -> dict:
    """precision/recall/coverage/auc, exactly as `get_metrics` computes them."""
    result = calculate_prc(scores_all=scores, is_correct=is_correct, n_spectra=n)
    result["auc"] = calculate_auc(get_prc_curve(scores_all=scores, is_correct=is_correct, n_spectra=n))
    result["n"] = n
    return result


def combinations() -> list[tuple[str, str, str, bool, bool]]:
    """(level, evaluation, ambiguity_label, allow_il, allow_deamidation) for every reported cell."""
    out = []
    for level in LEVELS:
        out.append((level, "mass", "", False, False))
        for suffix, flags in AMBIGUITY_COMBOS.items():
            out.append((level, "exact", suffix.lstrip("_"), flags["allow_il"], flags["allow_deamidation"]))
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("samples_dir", type=Path, help="Directory of <dataset>.csv prediction files.")
    parser.add_argument("--out", type=Path, required=True, help="Output directory.")
    parser.add_argument("--label", default="", help="Run label recorded in the metrics table, e.g. 'greedy_v1_3'.")
    parser.add_argument(
        "--save-intermediate",
        action="store_true",
        help="Also write one parquet per dataset with the per-spectrum match columns, for paired_stats.py.",
    )
    parser.add_argument("--datasets", nargs="+", help="Score only these datasets instead of every CSV found.")
    args = parser.parse_args()

    csv_paths = sorted(args.samples_dir.glob("*.csv"))
    if args.datasets:
        wanted = set(args.datasets)
        csv_paths = [p for p in csv_paths if p.stem in wanted]
    if not csv_paths:
        raise SystemExit(f"no prediction CSVs found in {args.samples_dir}")

    args.out.mkdir(parents=True, exist_ok=True)
    if args.save_intermediate:
        (args.out / "intermediate").mkdir(exist_ok=True)

    scorer = _ScoresNoFasta()
    rows = []
    # Pooled arrays are accumulated per combination rather than by concatenating the
    # intermediates, so peak memory stays at one dataset plus the flat score vectors.
    pooled: dict[tuple, list] = {combo[:3]: [[], [], 0] for combo in combinations()}

    for csv_path in csv_paths:
        dataset = csv_path.stem
        print(f"[{dataset}] reading {csv_path}", flush=True)
        frame, diagnostics = build_standard_frame(csv_path, dataset)
        intermediate = scorer.generate_intermediate(frame)
        print(
            f"[{dataset}] {diagnostics['n_rows']:,} spectra, "
            f"{diagnostics['unparseable_prediction']:,} unparseable predictions, "
            f"aa_scores {'broadcast' if diagnostics['aa_scores_broadcast'] else diagnostics['token_score_column']}",
            flush=True,
        )

        for level, evaluation, ambiguity, allow_il, allow_deamidation in combinations():
            scores, is_correct, n = score_arrays(intermediate, level, evaluation, allow_il, allow_deamidation)
            result = metrics_from_arrays(scores, is_correct, n)
            rows.append(
                {
                    "run": args.label,
                    "dataset": dataset,
                    "level": level,
                    "evaluation": evaluation,
                    "ambiguity": ambiguity,
                    **{k: result[k] for k in ("precision", "recall", "coverage", "auc", "n")},
                    **diagnostics,
                }
            )
            bucket = pooled[(level, evaluation, ambiguity)]
            bucket[0].append(scores)
            bucket[1].append(is_correct)
            bucket[2] += n

        if args.save_intermediate:
            keep = [
                c
                for c in intermediate.columns
                # Peptidoform objects and the ragged per-residue arrays do not survive a
                # parquet round-trip; the downstream scripts key on match_type and IDs.
                if c not in {"peptidoform", "peptidoform_ground_truth", "aa_scores", "bare"}
                and not c.startswith(("aa_matches_", "aa_exact_"))
            ]
            intermediate[keep].to_parquet(args.out / "intermediate" / f"{dataset}.parquet", index=False)

        del frame, intermediate

    for (level, evaluation, ambiguity), (score_chunks, correct_chunks, n) in pooled.items():
        result = metrics_from_arrays(np.concatenate(score_chunks), np.concatenate(correct_chunks), n)
        rows.append(
            {
                "run": args.label,
                "dataset": "__ALL__",
                "level": level,
                "evaluation": evaluation,
                "ambiguity": ambiguity,
                **{k: result[k] for k in ("precision", "recall", "coverage", "auc", "n")},
            }
        )

    metrics = pd.DataFrame(rows)
    metrics_path = args.out / "metrics.csv"
    metrics.to_csv(metrics_path, index=False)
    print(f"\nwrote {metrics_path}")

    pooled_view = metrics[metrics["dataset"] == "__ALL__"].copy()
    pooled_view["metric"] = (
        pooled_view["level"]
        + "/"
        + pooled_view["evaluation"]
        + pooled_view["ambiguity"].map(lambda a: f"+{a}" if a else "")
    )
    print("\npooled across all datasets:\n")
    print(pooled_view[["metric", "precision", "recall", "coverage", "auc", "n"]].round(4).to_string(index=False))


if __name__ == "__main__":
    main()
