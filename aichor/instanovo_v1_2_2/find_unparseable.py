"""Identify the predicted peptidoforms ProteoBench silently drops, and attribute the failure.

``ParseSettingsDeNovo.convert_to_standard_format`` wraps construction in a bare ``except``:

    def convert_to_peptidoform(proforma):
        try:
            return Peptidoform(proforma)
        except:
            return None
    ...
    df = df.dropna(subset="peptidoform")

so a prediction that cannot be parsed vanishes from the benchmark with no record of what
it was or why it failed. That is what makes the refined modes' coverage 0.99996 instead of
1.0. This script re-runs the same construction, keeps the exceptions, and separates the
layers to answer *whose* parser rejects the string:

* ``psm_utils.Peptidoform`` -- the class ProteoBench actually calls
* ``pyteomics.proforma.parse`` -- what psm_utils delegates to

If pyteomics rejects it, the next question is whether the string is valid ProForma (a
pyteomics bug) or whether InstaNovo emitted something the spec does not allow.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_sweep import fetch_predictions, finalize_outputs  # noqa: E402


def classify(sequence: str) -> dict:
    """Try both layers on one sequence and record what each does."""
    result = {"sequence": sequence}
    try:
        from psm_utils import Peptidoform

        Peptidoform(sequence)
        result["psm_utils"] = "ok"
    except Exception as error:
        result["psm_utils"] = f"{type(error).__name__}: {error}"

    try:
        from pyteomics import proforma

        proforma.parse(sequence)
        result["pyteomics"] = "ok"
    except Exception as error:
        result["pyteomics"] = f"{type(error).__name__}: {error}"
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--predictions", required=True, help="raw_predictions.csv (s3:// or local)")
    ap.add_argument("--mode", required=True)
    ap.add_argument("--work-dir", default="/workspace/proteobench_unparseable")
    ap.add_argument("--output-prefix", default="instanovo_v1_2_2_unparseable")
    args = ap.parse_args()

    work_dir = Path(args.work_dir) / args.mode
    work_dir.mkdir(parents=True, exist_ok=True)
    raw = fetch_predictions(args.predictions, work_dir / "raw_predictions.csv")

    header = pd.read_csv(raw, nrows=0).columns.tolist()
    usecols = [c for c in ("spectrum_id", "predictions") if c in header]
    df = pd.read_csv(raw, usecols=usecols, low_memory=False)
    print(f"[{args.mode}] {len(df):,} predictions", flush=True)

    sequences = df["predictions"]
    n_null = int(sequences.isna().sum())
    unique = sorted({str(s) for s in sequences.dropna().unique()})
    print(f"  null predictions: {n_null:,}", flush=True)
    print(f"  unique non-null sequences: {len(unique):,}", flush=True)

    # Only the failures are interesting, but classify() is cheap relative to the download.
    from psm_utils import Peptidoform

    failing = []
    for seq in unique:
        try:
            Peptidoform(seq)
        except Exception:
            failing.append(seq)
    print(f"  unique sequences psm_utils cannot parse: {len(failing):,}", flush=True)

    detail = [classify(seq) for seq in failing]
    counts = Counter()
    rows = []
    for entry in detail:
        seq = entry["sequence"]
        affected = df.index[df["predictions"].astype(str) == seq]
        spectrum_ids = df.loc[affected, "spectrum_id"].astype(str).tolist() if "spectrum_id" in df.columns else []
        counts[entry["pyteomics"].split(":")[0]] += len(affected)
        rows.append({
            "mode": args.mode,
            "sequence": seq,
            "n_spectra": len(affected),
            "spectrum_ids": ";".join(spectrum_ids[:20]),
            "psm_utils": entry["psm_utils"],
            "pyteomics": entry["pyteomics"],
        })
        print(f"\n  sequence : {seq!r}", flush=True)
        print(f"    spectra  : {len(affected)}  e.g. {spectrum_ids[:5]}", flush=True)
        print(f"    psm_utils: {entry['psm_utils'][:160]}", flush=True)
        print(f"    pyteomics: {entry['pyteomics'][:160]}", flush=True)

    total_dropped = sum(r["n_spectra"] for r in rows) + n_null
    print(f"\n[{args.mode}] spectra dropped: {total_dropped:,} of {len(df):,} "
          f"(coverage {1 - total_dropped/len(df):.6f})", flush=True)
    print(f"  by pyteomics verdict: {dict(counts)}", flush=True)

    out = pd.DataFrame(rows)
    out.to_csv(work_dir / "unparseable.csv", index=False)
    (work_dir / "unparseable.json").write_text(
        json.dumps({"mode": args.mode, "n_predictions": len(df), "n_null": n_null,
                    "n_unique": len(unique), "failures": rows}, indent=2, default=str),
        encoding="utf-8")
    finalize_outputs(Path(args.work_dir), args.output_prefix)
    return 0


if __name__ == "__main__":
    sys.exit(main())
