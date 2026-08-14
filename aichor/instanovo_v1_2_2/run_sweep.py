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
import traceback
from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.request import urlretrieve

import pandas as pd


DEFAULT_DATA_URL = "https://proteobench.cubimed.rub.de/raws/DeNovo-HCD/nine_species_balanced_De_Novo.mgf.gz"
DEFAULT_INSTANOVO_MODEL = "instanovo-v1.2.0"
DEFAULT_INSTANOVO_PLUS_MODEL = "instanovoplus-v1.1.0"
# Small MGF for --smoke wiring checks. There is no sensible default, so point
# PROTEOBENCH_SMOKE_MGF at one or pass --input-mgf.
SMOKE_MGF_VAR = "PROTEOBENCH_SMOKE_MGF"


@dataclass(frozen=True)
class RunConfig:
    name: str
    num_beams: int
    use_knapsack: bool
    with_refinement: bool
    # Run InstaNovo+ on its own via `instanovo diffusion predict` instead of the combined
    # transformer path. With --no-refinement the diffusion decoder gets initial_sequence=None,
    # so it starts from a uniform sample and runs the full reverse process, rather than
    # refining a transformer prediction.
    diffusion_only: bool = False

    @property
    def decoding_strategy(self) -> str:
        if self.diffusion_only:
            return "diffusion sampling"
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
    RunConfig("diffusion_only", 1, False, False, diffusion_only=True),
]


# Environment variables InstaNovo inspects to decide it is running on a managed compute
# platform (they hold a path for TensorBoard logs). When one is set,
# ``S3FileHandler._aichor_enabled()`` additionally requires an endpoint variable and
# raises AssertionError if it is absent -- at the end of `instanovo predict`, after a full
# inference pass and after the predictions have already been written locally, during an
# optional extra upload.
#
# This is specific to the pinned instanovo 1.2.2, which only accepts the endpoint under the
# name ``S3_ENDPOINT``. Later versions read ``AWS_ENDPOINT_URL`` instead, which managed
# platforms do set, so they need no intervention: once INSTANOVO_INSTALL_SPEC moves past
# 1.2.2, this stripping and HOSTED_PLATFORM_MARKERS can be deleted.
HOSTED_PLATFORM_MARKERS = ("AICHOR_LOGS_PATH",)


def instanovo_env() -> dict[str, str]:
    """Environment for the InstaNovo subprocess, with hosted-platform detection disabled.

    This script writes predictions to local files and handles any upload itself, so the
    markers are hidden from the subprocess: InstaNovo then writes plain local files and
    skips the upload it would otherwise attempt. Harmless on versions that do not need it.
    """
    env = os.environ.copy()
    for marker in HOSTED_PLATFORM_MARKERS:
        env.pop(marker, None)
    return env


def run_command(command: list[str], log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as log:
        log.write(" ".join(command) + "\n\n")
        log.flush()
        try:
            subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True, env=instanovo_env())
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
        smoke_mgf = os.environ.get(SMOKE_MGF_VAR)
        if not smoke_mgf:
            raise SystemExit(
                f"--smoke needs a small MGF: set {SMOKE_MGF_VAR} or pass --input-mgf explicitly."
            )
        path = Path(smoke_mgf).expanduser()
        if not path.is_file():
            raise SystemExit(f"{SMOKE_MGF_VAR} points at {path}, which is not a file.")
        return [path.resolve()]

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


MAPPED_COLUMNS = ["spectrum_id", "predictions", "log_probs", "token_log_probs"]


def _columns_to_read(header: list[str]) -> list[str]:
    """The subset of columns the InstaNovo [mapper] can actually consume.

    A beam-search run stores every beam (`predictions_beam_0..9` plus per-beam log-probs
    and token log-probs), which is ~30 extra columns and turns a 428MB greedy CSV into
    3.3GB. None of it is used for scoring, so don't pay to load it.
    """
    wanted = {"predictions"}
    wanted.add("spectrum_id" if "spectrum_id" in header else "scan_number")
    wanted.add("log_probs" if "log_probs" in header else "prediction_log_probability")
    if "token_log_probs" in header:
        wanted.add("token_log_probs")
    for fb in ("prediction_token_log_probabilities", "instanovoplus_prediction_token_log_probabilities"):
        if fb in header:
            wanted.add(fb)
    return [c for c in header if c in wanted]


def normalise_prediction_columns(input_csv: Path, output_csv: Path, trim: bool = False) -> None:
    if trim:
        header = pd.read_csv(input_csv, nrows=0).columns.tolist()
        usecols = _columns_to_read(header)
        print(f"  reading {len(usecols)}/{len(header)} columns: {usecols}", flush=True)
        df = pd.read_csv(input_csv, low_memory=False, usecols=usecols)
    else:
        df = pd.read_csv(input_csv, low_memory=False)
    if "spectrum_id" not in df.columns and "scan_number" in df.columns:
        df["spectrum_id"] = df["scan_number"]

    if "log_probs" not in df.columns and "prediction_log_probability" in df.columns:
        df["log_probs"] = df["prediction_log_probability"]

    if "token_log_probs" not in df.columns:
        df["token_log_probs"] = pd.NA
    df["token_log_probs"] = df["token_log_probs"].astype("object")

    # Only fall back to per-token scores that belong to the *emitted* prediction. The
    # transformer-only columns (`instanovo_prediction_token_log_probabilities`) are
    # deliberately excluded: in a refinement run `predictions` holds the InstaNovo+
    # sequence, so pairing it with the transformer's per-token scores misaligns them
    # wherever refinement changed the peptide, and ProteoBench's collapse_aa_scores
    # then dies on "All arrays must be of the same length".
    missing = df["token_log_probs"].isna() | (df["token_log_probs"].astype(str).str.strip() == "")
    for fallback in (
        "prediction_token_log_probabilities",
        "instanovoplus_prediction_token_log_probabilities",
        "diffusion_token_log_probabilities",
    ):
        if fallback in df.columns:
            df.loc[missing, "token_log_probs"] = df.loc[missing, fallback]
            missing = df["token_log_probs"].isna() | (df["token_log_probs"].astype(str).str.strip() == "")

    # InstaNovo+ (1.2.2) declares but never fills its per-token column, so a refined run
    # has no per-residue scores at all. Drop the column entirely rather than shipping an
    # empty one: ParseSettingsDeNovo then broadcasts the peptide score across residues
    # (parse_settings.py "If AA scores are not provided, simulate them from peptide score"),
    # which is the documented handling for tools without per-residue scores and gets the
    # length right via get_length_peptidoform_with_nterm.
    if missing.all():
        print(
            "No per-token scores available for any row; dropping token_log_probs so "
            "ProteoBench broadcasts the peptide-level score instead.",
            flush=True,
        )
        df = df.drop(columns=["token_log_probs"])

    if trim:
        df = df[[c for c in MAPPED_COLUMNS if c in df.columns]]
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
        if config.diffusion_only:
            # `instanovo diffusion predict` runs InstaNovo+ alone. --no-refinement leaves
            # initial_sequence=None, which starts the reverse process from a uniform sample
            # instead of a transformer prediction. num_beams/use_knapsack are transformer
            # beam-search settings and are not passed here.
            command = [
                "instanovo",
                "diffusion",
                "predict",
                "--denovo",
                "--no-refinement",
                "--data-path",
                str(mgf),
                "--output-path",
                str(raw_csv),
                "--instanovo-plus-model",
                args.instanovo_plus_model,
            ]
            command.extend(args.extra_override)
            command_lines.append(" ".join(command))
            run_command(command, log_path)
            normalise_prediction_columns(raw_csv, normalised_csv)
            prediction_files.append(normalised_csv)
            continue

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


# Inference settings these runs actually used, for the submitted datapoint's parameter
# columns. Values come from instanovo 1.2.2's `configs/inference/default.yaml`, which is
# the config these runs used (no --config-name was passed):
#
#     max_length: 40            max_charge: 10
#     isotope_error_range: [0, 1]
#     filter_precursor_ppm: 20
#
# `precursor_mass_tolerance` carries its unit explicitly: the submission form asks for one
# ("including unit ppm, PPM or Da") and existing datapoints record bare numbers, so a
# reader cannot tell ppm from Da. InstaNovo filters in ppm.
#
# Spectrum-processing settings (n_peaks, min_mz, max_mz, min_intensity,
# remove_precursor_tol) are part of the model's data config inside the checkpoint rather
# than the inference config, so they are left blank rather than guessed.
INFERENCE_PARAMETERS: dict[str, Any] = {
    "n_peaks": "",
    "precursor_mass_tolerance": "20 ppm",
    "min_peptide_length": "",
    "max_peptide_length": "40",
    "min_mz": "",
    "max_mz": "",
    "min_intensity": "",
    "max_intensity": "",
    "tokens": "",
    "min_precursor_charge": "",
    "max_precursor_charge": "10",
    "remove_precursor_tol": "",
    "isotope_error_range": "[0, 1]",
}


def user_input_for(config: RunConfig, args: argparse.Namespace) -> dict[str, Any]:
    checkpoint = args.instanovo_model
    if config.diffusion_only:
        # No transformer is involved, so only the InstaNovo+ checkpoint applies.
        checkpoint = args.instanovo_plus_model
    elif config.with_refinement:
        checkpoint = f"{args.instanovo_model}; {args.instanovo_plus_model}"

    return {
        "software_version": "1.2.2",
        "checkpoint": checkpoint,
        "n_beams": "" if config.diffusion_only else str(config.num_beams),
        **INFERENCE_PARAMETERS,
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

    # convert_to_standard_format() requires every [mapper] key to be a column, so when
    # normalise_prediction_columns dropped token_log_probs (no per-residue scores exist
    # for this run), drop it from the mapper too. ParseSettingsDeNovo then takes its
    # "simulate them from peptide score" path and broadcasts the peptide score.
    if "token_log_probs" not in input_df.columns and "token_log_probs" in parser.mapper:
        del parser.mapper["token_log_probs"]
        print("token_log_probs absent: peptide score will be broadcast across residues.", flush=True)

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


def iter_output_files(root: Path) -> list[Path]:
    """List files worth checksumming/syncing.

    Skips ``data/`` (the downloaded and decompressed input MGF, tens of GB that are
    already published upstream) and the knapsack cache, so syncing stays cheap enough
    to repeat after every decoding mode.
    """
    skip_dirs = {root / "data", root / "knapsack"}
    files = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(skip_dir in path.parents for skip_dir in skip_dirs):
            continue
        files.append(path)
    return files


def write_checksums(root: Path) -> None:
    lines = []
    for path in iter_output_files(root):
        if path.name == "SHA256SUMS":
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {path.relative_to(root)}")
    (root / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")


# Where finished results are copied to, in precedence order. A value may be a local
# directory, an ``s3://`` URI, or a bare bucket name (treated as ``s3://<bucket>/output``).
# Set one of these, or pass --sync-to, or leave all unset to keep results in --work-dir.
OUTPUT_PATH_VARS = ("PROTEOBENCH_OUTPUT_PATH", "AICHOR_OUTPUT_PATH")

# Endpoint for S3-compatible object storage, in precedence order. The service-specific
# ``AWS_ENDPOINT_URL_S3`` overrides the global ``AWS_ENDPOINT_URL`` by AWS SDK convention;
# ``S3_ENDPOINT`` is accepted as an older spelling. All unset means "use the provider
# default", which is what a real AWS account wants.
S3_ENDPOINT_VARS = ("AWS_ENDPOINT_URL_S3", "AWS_ENDPOINT_URL", "S3_ENDPOINT")


def _env_value(*names: str) -> str | None:
    """First of ``names`` set to something non-blank, whitespace-trimmed.

    Values are stripped because a platform can export a path or URL with surrounding
    whitespace (observed: ``AWS_ENDPOINT_URL`` with a leading space), which some clients
    parse as a relative path rather than a URL. A whitespace-only value counts as unset.
    """
    for name in names:
        value = os.environ.get(name)
        if value and value.strip():
            return value.strip()
    return None


def resolve_output_target(explicit: str | None = None) -> str | None:
    """The destination for finished results, or None to leave them in the work directory."""
    if explicit and explicit.strip():
        return explicit.strip()
    return _env_value(*OUTPUT_PATH_VARS)


def sync_outputs(local_root: Path, output_prefix: str, target: str | None = None) -> None:
    target = resolve_output_target(target)
    if not target:
        return

    if not target.startswith("s3://") and not _looks_like_bucket(target):
        dest = Path(target).expanduser() / output_prefix
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(local_root, dest, ignore=shutil.ignore_patterns("data", "knapsack"))
        return

    s3_target = target if target.startswith("s3://") else f"s3://{target}/output"
    s3_target = s3_target.rstrip("/") + f"/{output_prefix}"
    upload_tree_to_s3(local_root, s3_target)


def _looks_like_bucket(target: str) -> bool:
    """True for a bare bucket name, i.e. no path separator and not an existing local dir."""
    return "/" not in target and not Path(target).is_dir()


def s3_endpoint_url() -> str | None:
    """Endpoint override for S3-compatible storage, or None to use the provider default."""
    return _env_value(*S3_ENDPOINT_VARS)


def s3_filesystem():
    """An s3fs handle configured from the ambient S3 credentials and endpoint."""
    import s3fs

    client_kwargs = {}
    endpoint_url = s3_endpoint_url()
    if endpoint_url:
        client_kwargs["endpoint_url"] = endpoint_url

    return s3fs.S3FileSystem(
        key=os.environ.get("AWS_ACCESS_KEY_ID"),
        secret=os.environ.get("AWS_SECRET_ACCESS_KEY"),
        token=os.environ.get("AWS_SESSION_TOKEN"),
        client_kwargs=client_kwargs,
    )


def fetch_predictions(source: str, dest: Path) -> Path:
    """Fetch a predictions CSV from S3 (or copy it from a local path)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not source.startswith("s3://"):
        local = Path(source).resolve()
        if local != dest.resolve():
            shutil.copy2(local, dest)
        return dest

    fs = s3_filesystem()
    remote = source[len("s3://") :]
    print(f"Downloading {source} -> {dest}", flush=True)
    fs.get(remote, str(dest))
    return dest


def upload_tree_to_s3(local_root: Path, s3_target: str) -> None:
    import s3fs

    client_kwargs = {}
    endpoint_url = s3_endpoint_url()
    if endpoint_url:
        client_kwargs["endpoint_url"] = endpoint_url

    fs = s3fs.S3FileSystem(
        key=os.environ.get("AWS_ACCESS_KEY_ID"),
        secret=os.environ.get("AWS_SECRET_ACCESS_KEY"),
        token=os.environ.get("AWS_SESSION_TOKEN"),
        client_kwargs=client_kwargs,
    )
    fs.makedirs(s3_target, exist_ok=True)

    uploaded = 0
    for path in iter_output_files(local_root):
        relative_path = path.relative_to(local_root).as_posix()
        fs.put(str(path), f"{s3_target}/{relative_path}")
        uploaded += 1
    print(f"Uploaded {uploaded} files to {s3_target}", flush=True)


def finalize_outputs(work_dir: Path, output_prefix: str, target: str | None = None) -> None:
    comments = Path(__file__).with_name("comments_for_submission.md")
    if comments.exists():
        shutil.copy2(comments, work_dir / "comments_for_submission.md")
    write_checksums(work_dir)
    sync_outputs(work_dir, output_prefix, target)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--smoke", action="store_true", help="Run on the small local smoke-test MGF and skip metrics.")
    mode.add_argument("--full", action="store_true", help="Run on the full ProteoBench dataset and compute metrics.")
    parser.add_argument("--input-mgf", help="Use a specific MGF file instead of downloading the full dataset.")
    parser.add_argument("--input-dir", help="Use all .mgf/.mgf.gz files in this directory.")
    parser.add_argument("--work-dir", default="outputs", help="Local working/output directory.")
    parser.add_argument("--output-prefix", default="instanovo_v1_2_2", help="Prefix used under the output target when syncing results.")
    parser.add_argument(
        "--sync-to",
        help=(
            "Where to copy results when the run finishes: a local directory, an s3:// URI, or a bucket "
            f"name. Defaults to the first of {', '.join(OUTPUT_PATH_VARS)} that is set; if none are, "
            "results stay in --work-dir."
        ),
    )
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
    parser.add_argument(
        "--only",
        action="append",
        default=[],
        choices=[config.name for config in RUN_MATRIX],
        help="Run only the named decoding mode(s) instead of the full matrix. Repeatable.",
    )
    parser.add_argument(
        "--metrics-from",
        action="append",
        default=[],
        metavar="MODE=PATH",
        help=(
            "Skip inference: score an existing predictions CSV. PATH may be an s3:// URI or a "
            "local file. Repeatable, e.g. --metrics-from greedy=s3://bucket/key/raw_predictions.csv. "
            "Scoring needs no GPU but does need ~16GB+ RAM, since the intermediate always expands "
            "to the full ground-truth row count."
        ),
    )
    return parser.parse_args()


def parse_metrics_from(entries: list[str]) -> list[tuple[RunConfig, str]]:
    """Parse ``MODE=PATH`` pairs into (RunConfig, source) tuples."""
    by_name = {config.name: config for config in RUN_MATRIX}
    parsed = []
    for entry in entries:
        if "=" not in entry:
            raise ValueError(f"--metrics-from expects MODE=PATH, got {entry!r}")
        mode, _, source = entry.partition("=")
        mode, source = mode.strip(), source.strip()
        if mode not in by_name:
            raise ValueError(f"Unknown mode {mode!r}. Choose from: {', '.join(sorted(by_name))}")
        if not source:
            raise ValueError(f"--metrics-from {entry!r} has an empty path")
        parsed.append((by_name[mode], source))
    return parsed


def report_proteobench_install() -> None:
    """Log where ProteoBench resolves from and whether its TOML data files are present.

    A non-editable install that drops package data yields a FileNotFoundError deep in
    ParseSettingsBuilder, so confirm the data is reachable before doing any work.
    """
    try:
        import proteobench
        from proteobench.modules.constants import MODULE_SETTINGS_DIRS

        pkg_dir = Path(proteobench.__file__).resolve().parent
        settings_toml = pkg_dir / "io" / "parsing" / "io_parse_settings" / "parse_settings_files.toml"
        denovo_dir = Path(MODULE_SETTINGS_DIRS["denovo_DDA_HCD"])
        print(f"proteobench {getattr(proteobench, '__version__', '?')} at {pkg_dir}", flush=True)
        print(f"  parse_settings_files.toml exists: {settings_toml.is_file()} ({settings_toml})", flush=True)
        print(f"  denovo settings dir exists: {denovo_dir.is_dir()} ({denovo_dir})", flush=True)
        if denovo_dir.is_dir():
            print(f"  denovo settings contents: {sorted(p.name for p in denovo_dir.iterdir())}", flush=True)
    except Exception as error:
        print(f"could not introspect proteobench install: {type(error).__name__}: {error}", file=sys.stderr, flush=True)


def run_metrics_only(args: argparse.Namespace, work_dir: Path, output_dir: Path) -> dict[str, dict[str, Any]]:
    """Score already-computed predictions, without touching a GPU."""
    report_proteobench_install()
    requested = parse_metrics_from(args.metrics_from)
    print(f"Metrics-only for {len(requested)} mode(s): {', '.join(c.name for c, _ in requested)}", flush=True)

    metrics_by_run: dict[str, dict[str, Any]] = {}
    failures: list[str] = []
    for config, source in requested:
        run_dir = output_dir / config.name
        run_dir.mkdir(parents=True, exist_ok=True)
        try:
            raw_csv = fetch_predictions(source, run_dir / "raw_predictions.csv")
            normalised = run_dir / "results.csv"
            normalise_prediction_columns(raw_csv, normalised, trim=True)
            print(f"[{config.name}] scoring ...", flush=True)
            metrics_by_run[config.name] = compute_metrics(normalised, config, args, run_dir)
            print(f"[{config.name}] done", flush=True)
        except Exception as error:  # keep going: one bad mode must not sink the others
            failures.append(config.name)
            print(f"[{config.name}] FAILED: {type(error).__name__}: {error}", file=sys.stderr, flush=True)
            traceback.print_exc()
            sys.stderr.flush()
        # Sync as each mode lands so partial results survive.
        finalize_outputs(work_dir, args.output_prefix, getattr(args, "sync_to", None))

    if failures:
        print(f"Modes that failed: {', '.join(failures)}", file=sys.stderr, flush=True)
    run_metrics_only.failures = failures  # surfaced by main() so a partial run exits non-zero
    return metrics_by_run


def select_run_matrix(only: list[str]) -> list[RunConfig]:
    """Return the requested subset of RUN_MATRIX, preserving matrix order."""
    if not only:
        return RUN_MATRIX
    requested = set(only)
    return [config for config in RUN_MATRIX if config.name in requested]


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
        if args.metrics_from:
            metrics_by_run = run_metrics_only(args, work_dir, output_dir)
            if metrics_by_run:
                summary = flatten_metrics(metrics_by_run)
                summary.to_csv(work_dir / "metrics_summary.csv", index=False)
                (work_dir / "metrics_summary.json").write_text(
                    json.dumps(metrics_by_run, indent=2, default=str), encoding="utf-8"
                )
                print(f"\n{summary.to_string(index=False)}", flush=True)
            else:
                print("No metrics were produced.", file=sys.stderr, flush=True)
                return 1
            # Exit non-zero when any mode failed, even though others succeeded and synced:
            # otherwise AIchor reports "Succeeded" for a partial run and the failure is
            # only visible by reading the logs.
            failures = getattr(run_metrics_only, "failures", [])
            return 1 if failures else 0

        mgf_files = resolve_input_files(args, data_dir)
        run_matrix = select_run_matrix(args.only)
        print(f"Running {len(run_matrix)} mode(s): {', '.join(config.name for config in run_matrix)}", flush=True)
        metrics_by_run: dict[str, dict[str, Any]] = {}
        for config in run_matrix:
            run_dir = output_dir / config.name
            run_dir.mkdir(parents=True, exist_ok=True)
            results_csv = run_instanovo(config, mgf_files, run_dir, args)
            if args.full or args.compute_smoke_metrics:
                metrics_by_run[config.name] = compute_metrics(results_csv, config, args, run_dir)
            # Sync after every mode so a later failure or eviction cannot discard
            # work that already finished.
            finalize_outputs(work_dir, args.output_prefix, getattr(args, "sync_to", None))

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
            finalize_outputs(work_dir, args.output_prefix, getattr(args, "sync_to", None))
        except Exception as error:
            if pending_error:
                print(f"Failed to finalize Aichor outputs: {error}", file=sys.stderr)
            else:
                raise
    return 0


if __name__ == "__main__":
    sys.exit(main())
