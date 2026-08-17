"""Score completed internal held-out runs with ProteoBench's metrics, on AIchor.

`score_with_proteobench.py` scores a local directory of prediction CSVs. This driver runs the
same scoring where the data already is, which for these runs is the only practical option: a
single run's `samples/` prefix is ~920 MB, the comparisons worth making need six of them, and
the adapter's peak memory is a multiple of the file size again — `token_log_probs` parses into
per-residue float lists and every row builds two `Peptidoform` objects.

**Datasets are streamed one at a time and deleted immediately after scoring.** Peak disk is
therefore one CSV (~170 MB at the largest), not one run (~920 MB) and certainly not six
(~5.5 GB). Peak memory is one dataset's intermediate. Only `metrics.csv` travels back, which
is kilobytes.

Pooled metrics re-rank the concatenated score vectors rather than averaging per-dataset AUCs,
matching `score_with_proteobench.py`; averaging AUCs across datasets is not the AUC of the
pooled ranking, and the datasets here differ a lot in difficulty.

Usage
-----
    score_runs_aichor.py --runs instanovo_v1_3_133res_test_greedy instanovo_v1_2_2_test_greedy

Runs whose prefix does not exist yet are skipped with a warning rather than failing the job,
so the same command can be re-issued as more of the matrix lands.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from score_with_proteobench import (  # noqa: E402
    _ScoresNoFasta,
    build_standard_frame,
    combinations,
    metrics_from_arrays,
    score_arrays,
)

# AWS_ENDPOINT_URL_S3 overrides the global AWS_ENDPOINT_URL by SDK convention; S3_ENDPOINT is
# an older spelling. Same precedence as run_sweep.py, and the same reason for stripping:
# AIchor has been observed exporting AWS_ENDPOINT_URL with a leading space, which some clients
# parse as a relative path rather than a URL.
S3_ENDPOINT_VARS = ("AWS_ENDPOINT_URL_S3", "AWS_ENDPOINT_URL", "S3_ENDPOINT")
DEFAULT_S3_ROOT = "s3://dtu-denovo-s-2e6da747d6d34f62-outputs/evaluation"


def _env_value(*names: str) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value and value.strip():
            return value.strip()
    return None


def s3_filesystem():
    import s3fs

    client_kwargs = {}
    endpoint_url = _env_value(*S3_ENDPOINT_VARS)
    if endpoint_url:
        client_kwargs["endpoint_url"] = endpoint_url
    return s3fs.S3FileSystem(
        key=os.environ.get("AWS_ACCESS_KEY_ID"),
        secret=os.environ.get("AWS_SECRET_ACCESS_KEY"),
        token=os.environ.get("AWS_SESSION_TOKEN"),
        client_kwargs=client_kwargs,
    )


def score_one_run(fs, s3_root: str, run_name: str, staging: Path, save_intermediate: bool) -> pd.DataFrame:
    """Score every dataset of one run, streaming each CSV and deleting it after use."""
    prefix = f"{s3_root.rstrip('/')}/{run_name}/samples"
    remote = prefix[len("s3://") :]
    if not fs.exists(remote):
        print(f"[{run_name}] no samples prefix at {prefix}; skipping", file=sys.stderr, flush=True)
        return pd.DataFrame()

    csv_keys = sorted(k for k in fs.ls(remote) if k.endswith(".csv"))
    if not csv_keys:
        print(f"[{run_name}] samples prefix is empty; skipping", file=sys.stderr, flush=True)
        return pd.DataFrame()
    print(f"[{run_name}] {len(csv_keys)} datasets", flush=True)

    scorer = _ScoresNoFasta()
    rows = []
    pooled: dict[tuple, list] = {combo[:3]: [[], [], 0] for combo in combinations()}

    for key in csv_keys:
        dataset = Path(key).stem
        local = staging / f"{dataset}.csv"
        fs.get(key, str(local))
        size_mb = local.stat().st_size / 1e6
        print(f"[{run_name}/{dataset}] fetched {size_mb:.0f} MB", flush=True)

        try:
            frame, diagnostics = build_standard_frame(local, dataset)
            intermediate = scorer.generate_intermediate(frame)
            print(
                f"[{run_name}/{dataset}] {diagnostics['n_rows']:,} spectra, "
                f"{diagnostics['unparseable_prediction']:,} unparseable, "
                f"aa_scores {'broadcast' if diagnostics['aa_scores_broadcast'] else diagnostics['token_score_column']}",
                flush=True,
            )

            for level, evaluation, ambiguity, allow_il, allow_deamidation in combinations():
                scores, is_correct, n = score_arrays(intermediate, level, evaluation, allow_il, allow_deamidation)
                result = metrics_from_arrays(scores, is_correct, n)
                rows.append(
                    {
                        "run": run_name,
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

            if save_intermediate:
                keep = [
                    c
                    for c in intermediate.columns
                    if c not in {"peptidoform", "peptidoform_ground_truth", "aa_scores", "bare"}
                    and not c.startswith(("aa_matches_", "aa_exact_"))
                ]
                out_dir = staging.parent / "intermediate" / run_name
                out_dir.mkdir(parents=True, exist_ok=True)
                intermediate[keep].to_parquet(out_dir / f"{dataset}.parquet", index=False)

            del frame, intermediate
        finally:
            # Delete before the next dataset regardless of outcome; the point of streaming is
            # that only one CSV is ever resident.
            local.unlink(missing_ok=True)

    for (level, evaluation, ambiguity), (score_chunks, correct_chunks, n) in pooled.items():
        if not score_chunks:
            continue
        result = metrics_from_arrays(np.concatenate(score_chunks), np.concatenate(correct_chunks), n)
        rows.append(
            {
                "run": run_name,
                "dataset": "__ALL__",
                "level": level,
                "evaluation": evaluation,
                "ambiguity": ambiguity,
                **{k: result[k] for k in ("precision", "recall", "coverage", "auc", "n")},
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--runs", nargs="+", required=True, help="Run names under the evaluation prefix.")
    parser.add_argument("--s3-root", default=DEFAULT_S3_ROOT)
    parser.add_argument("--out", default="s3://dtu-denovo-s-2e6da747d6d34f62-outputs/evaluation/_scored")
    parser.add_argument("--save-intermediate", action="store_true")
    args = parser.parse_args()

    fs = s3_filesystem()
    frames = []
    with tempfile.TemporaryDirectory(prefix="scoring-") as tmp:
        staging = Path(tmp) / "samples"
        staging.mkdir(parents=True)
        for run_name in args.runs:
            try:
                frames.append(score_one_run(fs, args.s3_root, run_name, staging, args.save_intermediate))
            except Exception as exc:  # one bad run must not lose the others' results
                print(f"[{run_name}] FAILED: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)

        combined = pd.concat([f for f in frames if not f.empty], ignore_index=True) if frames else pd.DataFrame()
        if combined.empty:
            raise SystemExit("no runs produced metrics")

        local_out = Path(tmp) / "metrics.csv"
        combined.to_csv(local_out, index=False)

        target = args.out.rstrip("/")
        fs.put(str(local_out), f"{target[len('s3://'):]}/metrics.csv")
        print(f"\nwrote {target}/metrics.csv", flush=True)

        intermediate_root = staging.parent / "intermediate"
        if args.save_intermediate and intermediate_root.exists():
            for path in sorted(intermediate_root.rglob("*.parquet")):
                rel = path.relative_to(intermediate_root).as_posix()
                fs.put(str(path), f"{target[len('s3://'):]}/intermediate/{rel}")
            print("uploaded intermediates", flush=True)

    pooled_view = combined[combined["dataset"] == "__ALL__"].copy()
    pooled_view["metric"] = (
        pooled_view["level"]
        + "/"
        + pooled_view["evaluation"]
        + pooled_view["ambiguity"].map(lambda a: f"+{a}" if a else "")
    )
    print("\npooled across all datasets, per run:\n", flush=True)
    print(
        pooled_view.pivot_table(index="metric", columns="run", values="precision")
        .round(4)
        .to_string()
    )
    print("\nAUC:\n", flush=True)
    print(pooled_view.pivot_table(index="metric", columns="run", values="auc").round(4).to_string())


if __name__ == "__main__":
    main()
