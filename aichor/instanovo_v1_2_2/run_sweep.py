from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.request import urlretrieve

import pandas as pd


DEFAULT_DATA_URL = "https://proteobench.cubimed.rub.de/raws/DeNovo-HCD/nine_species_balanced_De_Novo.mgf.gz"
DEFAULT_INSTANOVO_MODEL = "instanovo-v1.2.0"
DEFAULT_INSTANOVO_PLUS_MODEL = "instanovoplus-v1.1.0"
SMOKE_MGF = "/home/j-vangoey/code/InstaNovo-internal/data/small/small.mgf"


@dataclass(frozen=True)
class RunConfig:
    name: str
    num_beams: int
    use_knapsack: bool
    with_refinement: bool

    @property
    def decoding_strategy(self) -> str:
        if self.use_knapsack:
            return "knapsack beam search"
        if self.num_beams == 1:
            return "greedy search"
        return "beam search"


RUN_MATRIX = [
    RunConfig("greedy", 1, False, False),
    RunConfig("beam10", 10, False, False),
    RunConfig("knapsack_beam10", 10, True, False),
    RunConfig("greedy_refined", 1, False, True),
    RunConfig("beam10_refined", 10, False, True),
    RunConfig("knapsack_beam10_refined", 10, True, True),
]


def run_command(command: list[str], log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as log:
        log.write(" ".join(command) + "\n\n")
        log.flush()
        try:
            subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
        except subprocess.CalledProcessError:
            print(f"Command failed. Last lines from {log_path}:", file=sys.stderr)
            for line in tail_log(log_path):
                print(line.rstrip(), file=sys.stderr)
            raise


def tail_log(log_path: Path, lines: int = 200) -> deque[str]:
    with log_path.open("r", encoding="utf-8", errors="replace") as log:
        return deque(log, maxlen=lines)


def resolve_input_files(args: argparse.Namespace, data_dir: Path) -> list[Path]:
    if args.input_mgf:
        return [prepare_mgf(Path(args.input_mgf), data_dir)]

    if args.input_dir:
        files = sorted(Path(args.input_dir).glob("*.mgf")) + sorted(Path(args.input_dir).glob("*.mgf.gz"))
        if not files:
            raise FileNotFoundError(f"No .mgf or .mgf.gz files found in {args.input_dir}")
        return [prepare_mgf(path, data_dir) for path in files]

    if args.smoke:
        return [Path(SMOKE_MGF).resolve()]

    data_dir.mkdir(parents=True, exist_ok=True)
    download_path = data_dir / Path(DEFAULT_DATA_URL).name
    if not download_path.exists():
        urlretrieve(DEFAULT_DATA_URL, download_path)
    return [prepare_mgf(download_path, data_dir)]


def prepare_mgf(path: Path, data_dir: Path) -> Path:
    if path.suffix != ".gz":
        return path.resolve()

    data_dir.mkdir(parents=True, exist_ok=True)
    out_path = data_dir / path.name.removesuffix(".gz")
    if out_path.exists():
        return out_path.resolve()

    with gzip.open(path, "rb") as src, out_path.open("wb") as dst:
        shutil.copyfileobj(src, dst)
    return out_path.resolve()


def normalise_prediction_columns(input_csv: Path, output_csv: Path) -> None:
    df = pd.read_csv(input_csv, low_memory=False)
    if "spectrum_id" not in df.columns and "scan_number" in df.columns:
        df["spectrum_id"] = df["scan_number"]

    if "log_probs" not in df.columns and "prediction_log_probability" in df.columns:
        df["log_probs"] = df["prediction_log_probability"]

    if "token_log_probs" not in df.columns:
        df["token_log_probs"] = pd.NA
    df["token_log_probs"] = df["token_log_probs"].astype("object")

    missing = df["token_log_probs"].isna() | (df["token_log_probs"].astype(str).str.strip() == "")
    for fallback in (
        "prediction_token_log_probabilities",
        "instanovoplus_prediction_token_log_probabilities",
        "instanovo_prediction_token_log_probabilities",
        "diffusion_token_log_probabilities",
        "instanovo_token_log_probabilities",
    ):
        if fallback in df.columns:
            df.loc[missing, "token_log_probs"] = df.loc[missing, fallback]
            missing = df["token_log_probs"].isna() | (df["token_log_probs"].astype(str).str.strip() == "")

    df.to_csv(output_csv, index=False)


def run_instanovo(config: RunConfig, mgf_files: list[Path], run_dir: Path, args: argparse.Namespace) -> Path:
    prediction_files: list[Path] = []
    command_lines: list[str] = []
    start = time.time()
    for mgf in mgf_files:
        sample_name = mgf.stem
        sample_dir = run_dir / "samples" / sample_name
        raw_csv = sample_dir / "raw_predictions.csv"
        normalised_csv = sample_dir / "results.csv"
        log_path = sample_dir / "instanovo.log"
        command = [
            "instanovo",
            "predict",
            "--denovo",
            "--data-path",
            str(mgf),
            "--output-path",
            str(raw_csv),
            "--instanovo-model",
            args.instanovo_model,
        ]
        if config.with_refinement:
            command.extend(["--with-refinement", "--instanovo-plus-model", args.instanovo_plus_model])
        else:
            command.append("--no-refinement")

        command.extend(
            [
                f"num_beams={config.num_beams}",
                f"use_knapsack={str(config.use_knapsack).lower()}",
                f"knapsack_path={args.knapsack_path}",
            ]
        )
        command.extend(args.extra_override)
        command_lines.append(" ".join(command))
        run_command(command, log_path)
        normalise_prediction_columns(raw_csv, normalised_csv)
        prediction_files.append(normalised_csv)

    combined = run_dir / "results.csv"
    frames = [pd.read_csv(path, low_memory=False) for path in prediction_files]
    pd.concat(frames, ignore_index=True).to_csv(combined, index=False)

    metadata = {
        **asdict(config),
        "decoding_strategy": config.decoding_strategy,
        "instanovo_model": args.instanovo_model,
        "instanovo_plus_model": args.instanovo_plus_model if config.with_refinement else None,
        "knapsack_path": args.knapsack_path if config.use_knapsack else None,
        "extra_overrides": args.extra_override,
        "commands": command_lines,
        "input_files": [str(path) for path in mgf_files],
        "runtime_seconds": round(time.time() - start, 3),
        "result_rows": int(sum(len(frame) for frame in frames)),
    }
    (run_dir / "run_config.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return combined


def user_input_for(config: RunConfig, args: argparse.Namespace) -> dict[str, Any]:
    checkpoint = args.instanovo_model
    if config.with_refinement:
        checkpoint = f"{args.instanovo_model}; {args.instanovo_plus_model}"

    return {
        "software_version": "1.2.2",
        "checkpoint": checkpoint,
        "n_beams": str(config.num_beams),
        "n_peaks": "",
        "precursor_mass_tolerance": "",
        "min_peptide_length": "",
        "max_peptide_length": "",
        "min_mz": "",
        "max_mz": "",
        "min_intensity": "",
        "max_intensity": "",
        "tokens": "",
        "min_precursor_charge": "",
        "max_precursor_charge": "",
        "remove_precursor_tol": "",
        "isotope_error_range": "",
        "decoding_strategy": config.decoding_strategy,
        "comments_for_plotting": f"InstaNovo v1.2.2 {config.name}",
    }


def compute_metrics(results_csv: Path, config: RunConfig, args: argparse.Namespace, run_dir: Path) -> dict[str, Any]:
    from proteobench.datapoint.denovo_datapoint import DenovoDatapoint
    from proteobench.io.parsing.parse_denovo import load_input_file
    from proteobench.io.parsing.parse_settings import ParseSettingsBuilder
    from proteobench.modules.constants import MODULE_SETTINGS_DIRS
    from proteobench.score.denovoscores import DenovoScores

    input_df = load_input_file(str(results_csv), "InstaNovo")
    parser = ParseSettingsBuilder(
        parse_settings_dir=MODULE_SETTINGS_DIRS["denovo_DDA_HCD"],
        module_id="denovo_DDA_HCD",
    ).build_parser("InstaNovo")
    standard_format = parser.convert_to_standard_format(input_df)
    intermediate = DenovoScores().generate_intermediate(standard_format)
    intermediate.to_csv(run_dir / "intermediate.csv", index=False)
    datapoint = DenovoDatapoint.generate_datapoint(
        intermediate=intermediate,
        input_format="InstaNovo",
        user_input=user_input_for(config, args),
        evaluation_type="mass",
    )
    metrics = datapoint.to_dict()
    (run_dir / "datapoint.json").write_text(json.dumps(metrics, indent=2, default=str), encoding="utf-8")
    return metrics


def flatten_metrics(metrics_by_run: dict[str, dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for run_name, data in metrics_by_run.items():
        results = data.get("results", {})
        row = {"run_name": run_name}
        for level in ("peptide", "aa"):
            for evaluation in ("mass", "exact"):
                for metric in ("precision", "recall", "coverage"):
                    row[f"{level}_{evaluation}_{metric}"] = (
                        results.get(level, {}).get(evaluation, {}).get(metric)
                    )
        rows.append(row)
    return pd.DataFrame(rows)


def write_checksums(root: Path) -> None:
    lines = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name != "SHA256SUMS":
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            lines.append(f"{digest}  {path.relative_to(root)}")
    (root / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")


def sync_outputs(local_root: Path, output_prefix: str) -> None:
    target = os.environ.get("AICHOR_OUTPUT_PATH")
    if not target:
        return

    if target.startswith("/"):
        dest = Path(target) / output_prefix
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(local_root, dest)
        return

    s3_target = target if target.startswith("s3://") else f"s3://{target}/output"
    s3_target = s3_target.rstrip("/") + f"/{output_prefix}"
    subprocess.run(["aws", "s3", "sync", str(local_root), s3_target], check=True)


def finalize_outputs(work_dir: Path, output_prefix: str) -> None:
    comments = Path(__file__).with_name("comments_for_submission.md")
    if comments.exists():
        shutil.copy2(comments, work_dir / "comments_for_submission.md")
    write_checksums(work_dir)
    sync_outputs(work_dir, output_prefix)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--smoke", action="store_true", help="Run on the small local smoke-test MGF and skip metrics.")
    mode.add_argument("--full", action="store_true", help="Run on the full ProteoBench dataset and compute metrics.")
    parser.add_argument("--input-mgf", help="Use a specific MGF file instead of downloading the full dataset.")
    parser.add_argument("--input-dir", help="Use all .mgf/.mgf.gz files in this directory.")
    parser.add_argument("--work-dir", default="outputs", help="Local working/output directory.")
    parser.add_argument("--output-prefix", default="instanovo_v1_2_2", help="Prefix used when syncing to AICHOR_OUTPUT_PATH.")
    parser.add_argument("--knapsack-path", help="Shared InstaNovo knapsack cache directory.")
    parser.add_argument("--instanovo-model", default=DEFAULT_INSTANOVO_MODEL)
    parser.add_argument("--instanovo-plus-model", default=DEFAULT_INSTANOVO_PLUS_MODEL)
    parser.add_argument(
        "--extra-override",
        action="append",
        default=[],
        help="Additional InstaNovo Hydra override. Can be supplied multiple times.",
    )
    parser.add_argument("--compute-smoke-metrics", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.smoke and not args.full and not args.input_mgf and not args.input_dir:
        args.full = True

    work_dir = Path(args.work_dir).resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    if args.knapsack_path is None:
        args.knapsack_path = str(work_dir / "knapsack")
    data_dir = work_dir / "data"
    output_dir = work_dir / "runs"
    output_dir.mkdir(exist_ok=True)

    pending_error = False
    try:
        mgf_files = resolve_input_files(args, data_dir)
        metrics_by_run: dict[str, dict[str, Any]] = {}
        for config in RUN_MATRIX:
            run_dir = output_dir / config.name
            run_dir.mkdir(parents=True, exist_ok=True)
            results_csv = run_instanovo(config, mgf_files, run_dir, args)
            if args.full or args.compute_smoke_metrics:
                metrics_by_run[config.name] = compute_metrics(results_csv, config, args, run_dir)

        if metrics_by_run:
            summary = flatten_metrics(metrics_by_run)
            summary.to_csv(work_dir / "metrics_summary.csv", index=False)
            (work_dir / "metrics_summary.json").write_text(
                json.dumps(metrics_by_run, indent=2, default=str),
                encoding="utf-8",
            )
        else:
            (work_dir / "metrics_summary.csv").write_text("run_name,metrics_status\nsmoke,skipped\n", encoding="utf-8")
    except Exception:
        pending_error = True
        raise
    finally:
        try:
            finalize_outputs(work_dir, args.output_prefix)
        except Exception as error:
            if pending_error:
                print(f"Failed to finalize Aichor outputs: {error}", file=sys.stderr)
            else:
                raise
    return 0


if __name__ == "__main__":
    sys.exit(main())
