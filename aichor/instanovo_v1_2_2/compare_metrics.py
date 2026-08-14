"""Cross-check ProteoBench de novo metrics against InstaNovo's own ``Metrics`` class.

Both implementations are run over the *identical* (ground truth, prediction) pairs, taken
from ProteoBench's standardized dataframe, so the only differences left are the matching
algorithm and the mass tolerances:

* ProteoBench ``DenovoScores``: prefix + reverse-suffix walk, tolerances in **ppm**
  (``cum_mass_threshold=50``, ``ind_mass_threshold=20``; ``mass_diff(..., mode_is_da=False)``
  returns ``(a-b)/b*1e6``), plus I/L and deamidation ambiguity toggles.
* InstaNovo ``Metrics._novor_match``: single forward two-pointer walk over cumulative
  masses, tolerances in **absolute Da** (defaults 0.5 / 0.1).

InstaNovo's thresholds cannot express ppm, so we additionally sweep Da values chosen to
approximate ProteoBench's ppm tolerances at representative masses. This quantifies the
unit mismatch instead of asserting it.

Note on InstaNovo PR #749: that fix concerns ``predictor.calculate_metrics``, where log-only
ppm/confidence filters aliased and blanked ``predictions`` before the per-group metrics were
computed. This script calls ``Metrics`` directly on unfiltered pairs, which is the behaviour
the fix restores, so the numbers here are the post-fix ones by construction.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import traceback
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_sweep import (  # noqa: E402
    DEFAULT_INSTANOVO_MODEL,
    DEFAULT_INSTANOVO_PLUS_MODEL,
    RUN_MATRIX,
    fetch_predictions,
    normalise_prediction_columns,
    user_input_for,
)

# (cum_mass_threshold, ind_mass_threshold, label) in absolute Da for InstaNovo Metrics.
# ProteoBench uses 50 ppm cumulative / 20 ppm per residue; at ~1000 Da cumulative that is
# ~0.05 Da, and at a ~110 Da residue 20 ppm is ~0.0022 Da.
THRESHOLD_SETTINGS = [
    (0.5, 0.1, "InstaNovo defaults (0.5 / 0.1 Da)"),
    (0.1, 0.01, "10x tighter (0.1 / 0.01 Da)"),
    (0.05, 0.0022, "~ProteoBench-equivalent at 1000/110 Da (0.05 / 0.0022 Da)"),
]


def strip_charge(value) -> str:
    """Ground-truth peptidoforms are stored as ``SEQUENCE/charge``; drop the charge."""
    if value is None:
        return ""
    text = str(value)
    if text == "nan":
        return ""
    return re.sub(r"/\d+$", "", text)


def build_standard_format(predictions_csv: Path, run_dir: Path):
    """Parse predictions into ProteoBench's standardized dataframe."""
    from proteobench.io.parsing.parse_denovo import load_input_file
    from proteobench.io.parsing.parse_settings import ParseSettingsBuilder
    from proteobench.modules.constants import MODULE_SETTINGS_DIRS

    normalised = run_dir / "results.csv"
    normalise_prediction_columns(predictions_csv, normalised, trim=True)
    input_df = load_input_file(str(normalised), "InstaNovo")
    parser = ParseSettingsBuilder(
        parse_settings_dir=MODULE_SETTINGS_DIRS["denovo_DDA_HCD"],
        module_id="denovo_DDA_HCD",
    ).build_parser("InstaNovo")
    if "token_log_probs" not in input_df.columns and "token_log_probs" in parser.mapper:
        del parser.mapper["token_log_probs"]
    return parser.convert_to_standard_format(input_df)


def proteobench_metrics(standard_format, config, run_dir: Path) -> dict:
    """ProteoBench's own numbers over these pairs."""
    from proteobench.datapoint.denovo_datapoint import DenovoDatapoint
    from proteobench.score.denovoscores import DenovoScores

    intermediate = DenovoScores().generate_intermediate(standard_format.copy())
    # Reuse run_sweep's user_input_for: generate_datapoint indexes every parameter key
    # directly (n_peaks, min_mz, ...), so an abbreviated dict raises KeyError.
    args = SimpleNamespace(
        instanovo_model=DEFAULT_INSTANOVO_MODEL,
        instanovo_plus_model=DEFAULT_INSTANOVO_PLUS_MODEL,
    )
    datapoint = DenovoDatapoint.generate_datapoint(
        intermediate=intermediate,
        input_format="InstaNovo",
        user_input=user_input_for(config, args),
        evaluation_type="mass",
    )
    results = datapoint.to_dict()["results"]
    (run_dir / "proteobench_datapoint.json").write_text(
        json.dumps(datapoint.to_dict(), indent=2, default=str), encoding="utf-8"
    )
    return {
        "pep_precision": results["peptide"]["mass"]["precision"],
        "pep_recall": results["peptide"]["mass"]["recall"],
        "aa_precision": results["aa"]["mass"]["precision"],
        "aa_recall": results["aa"]["mass"]["recall"],
        "pep_exact_precision": results["peptide"]["exact"]["precision"],
    }


# Monoisotopic element masses, for resolving ProteoBench's `[Formula:...]` tokens.
_ELEMENT_MASSES = {"H": 1.0078250319, "C": 12.0, "N": 14.0030740052, "O": 15.9949146221, "S": 31.97207069}
_FORMULA_TOKEN = re.compile(r"^\[Formula:(.+)\]$")


def formula_mass(formula: str) -> float:
    """Monoisotopic mass of a formula like ``H-2C1O1`` (negative counts allowed).

    ProteoBench's ground truth uses these for composite N-terminal modifications that have
    no single UNIMOD id -- ``H-2C1O1`` is carbamylation (+43.0058) together with ammonia
    loss (-17.0265), i.e. +25.9793 Da. InstaNovo's residue set has no such token, so we
    teach it the mass rather than silently dropping those peptides.
    """
    total = 0.0
    for element, count in re.findall(r"([A-Z][a-z]?)(-?\d+)", formula):
        if element not in _ELEMENT_MASSES:
            raise KeyError(f"unknown element {element!r} in formula {formula!r}")
        total += _ELEMENT_MASSES[element] * int(count)
    return total


def extend_residue_set(residue_set, tokens: set[str]):
    """Return a ResidueSet that also knows any `[Formula:...]` tokens present in the data."""
    from instanovo.utils.residues import ResidueSet

    extra = {}
    for token in sorted(tokens):
        if token in residue_set.residue_masses:
            continue
        match = _FORMULA_TOKEN.match(token)
        if match:
            try:
                extra[token] = formula_mass(match.group(1))
            except KeyError as error:
                print(f"  cannot resolve {token}: {error}", flush=True)
    if not extra:
        return residue_set
    for token, mass in extra.items():
        print(f"  extending residue set: {token} -> {mass:.6f} Da", flush=True)
    return ResidueSet(
        residue_masses={**residue_set.residue_masses, **extra},
        residue_remapping=residue_set.residue_remapping,
    )


def instanovo_metrics(targets: list[str], predictions: list[str]) -> dict:
    """InstaNovo's Metrics at each threshold setting."""
    from instanovo.transformer.model import InstaNovo
    from instanovo.utils.metrics import Metrics

    print("loading instanovo-v1.2.0 for its residue set ...", flush=True)
    model, model_config = InstaNovo.from_pretrained("instanovo-v1.2.0")
    residue_set = model.residue_set
    print(f"  residue set size: {len(residue_set.vocab)}", flush=True)

    # Teach it any bracketed tokens the ProteoBench ground truth uses but InstaNovo lacks.
    data_tokens = set()
    for seq in targets:
        data_tokens.update(re.findall(r"\[[^\]]*\]", seq))
    residue_set = extend_residue_set(residue_set, {t for t in data_tokens if t.startswith("[Formula:")})

    # Drop pairs still containing tokens the residue set cannot mass -- report the count so
    # the exclusion is visible instead of silently changing the denominators.
    known = set(residue_set.residue_masses)
    def scorable(seq: str) -> bool:
        return all(tok in known or tok.strip("[]").startswith("UNIMOD") for tok in re.findall(r"\[[^\]]*\]", seq))

    keep = [i for i in range(len(targets)) if scorable(targets[i]) and scorable(predictions[i])]
    dropped = len(targets) - len(keep)
    if dropped:
        print(f"  excluded {dropped:,} of {len(targets):,} pairs with untokenizable residues", flush=True)
    targets = [targets[i] for i in keep]
    predictions = [predictions[i] for i in keep]

    out = {}
    for cum_thr, ind_thr, label in THRESHOLD_SETTINGS:
        metrics = Metrics(residue_set, isotope_error_range=[0, 1], cum_mass_threshold=cum_thr, ind_mass_threshold=ind_thr)
        aa_prec, aa_recall, pep_recall, pep_precision = metrics.compute_precision_recall(targets, predictions)
        out[label] = {
            "aa_precision": aa_prec,
            "aa_recall": aa_recall,
            "pep_recall": pep_recall,
            "pep_precision": pep_precision,
        }
        print(
            f"  [{label}] pep_prec={pep_precision:.6f} pep_recall={pep_recall:.6f} "
            f"aa_prec={aa_prec:.6f} aa_recall={aa_recall:.6f}",
            flush=True,
        )
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--predictions", required=True, help="raw_predictions.csv (s3:// or local)")
    ap.add_argument("--mode", required=True, choices=[c.name for c in RUN_MATRIX])
    ap.add_argument("--work-dir", default="/workspace/proteobench_compare")
    ap.add_argument("--output-prefix", default="instanovo_v1_2_2_metric_comparison")
    args = ap.parse_args()

    config = next(c for c in RUN_MATRIX if c.name == args.mode)
    run_dir = Path(args.work_dir) / args.mode
    run_dir.mkdir(parents=True, exist_ok=True)

    raw = fetch_predictions(args.predictions, run_dir / "raw_predictions.csv")
    sf = build_standard_format(raw, run_dir)
    print(f"standard format rows: {len(sf):,}", flush=True)

    # Same pairs for both implementations. Rows whose prediction is missing (spectra the
    # tool did not report) stay in as empty strings: ProteoBench charges them as unmatched
    # and InstaNovo's compute_precision_recall skips empty predictions for the precision
    # denominator while still counting them in recall -- report both so the difference in
    # denominators is visible rather than hidden.
    # Use the *native* strings on both sides, not psm_utils `Peptidoform` objects:
    #   - ground truth: the raw CSV value, e.g. "AFQSAYYNR/2" -> strip the charge suffix
    #   - predictions: `proforma`, which is the original InstaNovo output string
    # Stringifying a Peptidoform instead renders some modifications as `[Formula:...]`,
    # which InstaNovo's tokenizer cannot mass (KeyError: '[Formula:H-2C1O1]').
    targets = [strip_charge(x) for x in sf["peptidoform_ground_truth"].tolist()]
    preds = [str(x) if x is not None and str(x) != "nan" else "" for x in sf["proforma"].tolist()]
    n_empty = sum(1 for p in preds if not p or p == "nan")
    print(f"pairs: {len(targets):,}  (empty/missing predictions: {n_empty:,})", flush=True)
    print(f"  target sample:     {targets[:2]}", flush=True)
    print(f"  prediction sample: {preds[:2]}", flush=True)

    # Each pass costs several minutes, so a failure in one must not discard the other.
    pb: dict = {}
    ino: dict = {}
    try:
        pb = proteobench_metrics(sf, config, run_dir)
        print("\nProteoBench (50/20 ppm, prefix+suffix walk):", flush=True)
        for k, v in pb.items():
            print(f"  {k}: {v:.6f}", flush=True)
    except Exception as error:
        print(f"ProteoBench pass FAILED: {type(error).__name__}: {error}", file=sys.stderr, flush=True)
        traceback.print_exc()

    try:
        print("\nInstaNovo Metrics (absolute Da, _novor_match):", flush=True)
        ino = instanovo_metrics(targets, preds)
    except Exception as error:
        print(f"InstaNovo pass FAILED: {type(error).__name__}: {error}", file=sys.stderr, flush=True)
        traceback.print_exc()

    report = {
        "mode": args.mode,
        "n_pairs": len(targets),
        "n_empty_predictions": n_empty,
        "proteobench": pb,
        "instanovo": ino,
    }
    (run_dir / "metric_comparison.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    rows = []
    if pb:
        rows.append({"implementation": "ProteoBench (50/20 ppm)", **{k: pb.get(k) for k in ("pep_precision", "pep_recall", "aa_precision", "aa_recall")}})
    for label, vals in ino.items():
        rows.append({"implementation": f"InstaNovo {label}", **vals})
    table = pd.DataFrame(rows)
    table.to_csv(run_dir / "metric_comparison.csv", index=False)
    print(f"\n{table.to_string(index=False)}", flush=True)

    from run_sweep import finalize_outputs

    finalize_outputs(Path(args.work_dir), args.output_prefix)
    return 0 if (pb and ino) else 1


if __name__ == "__main__":
    sys.exit(main())
