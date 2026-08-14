# InstaNovo v1.2.2 ProteoBench Aichor Sweep

This directory is intentionally kept on the Aichor run branch, separate from the upstream ProteoBench support branch.

## Local Aichor CLI Setup

```bash
uv venv .venv-aichor
uv pip install --python .venv-aichor/bin/python "aichor-cli==3.0.1" --index https://aichor-python-packages.aichor.ai --index-strategy unsafe-best-match
.venv-aichor/bin/aichor --help
```

If the private Aichor Python package index requires authentication, configure that authentication first and rerun the `uv pip install` command.

## Smoke Test

The smoke test runs on a small MGF (given by `--input-mgf`, or `PROTEOBENCH_SMOKE_MGF`) and skips ProteoBench metric computation by default.

```bash
python aichor/instanovo_v1_2_2/run_sweep.py \
  --smoke \
  --input-mgf /path/to/small.mgf \
  --work-dir /tmp/proteobench-instanovo-smoke \
  --extra-override force_cpu=true \
  --extra-override fp16=false \
  --extra-override batch_size=4 \
  --extra-override num_workers=0
```

## Running Outside a Managed Platform

`run_sweep.py` needs no particular compute platform. It runs anywhere InstaNovo and
ProteoBench are installed and a GPU is available:

```bash
python run_sweep.py --full --only beam10_refined \
  --work-dir ./out \
  --sync-to ./published            # optional; omit to leave results in --work-dir
```

Results are copied to `--sync-to` when the run finishes. That may be a local directory, an
`s3://` URI, or a bucket name; if it is omitted, the first of `PROTEOBENCH_OUTPUT_PATH` or
`AICHOR_OUTPUT_PATH` that is set is used, and if none are, results simply stay in the work
directory. For `s3://` destinations, credentials and endpoint come from the standard
`AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / `AWS_SESSION_TOKEN` variables, with the
endpoint taken from `AWS_ENDPOINT_URL_S3`, `AWS_ENDPOINT_URL` or `S3_ENDPOINT` (in that
order) -- all unset means the provider default, which is what a plain AWS account wants.

Scoring predictions produced elsewhere needs no GPU:

```bash
python run_sweep.py --metrics-from beam10_refined=/path/to/raw_predictions.csv --work-dir ./out
```

Note that scoring expands to the full ground-truth row count regardless of how many
predictions are supplied, so it needs roughly 16GB of RAM.

## Full Aichor Run

The full run downloads the ProteoBench De Novo DDA-HCD combined MGF by default. If multiple MGF files are supplied through `--input-dir`, each mode is run on every MGF and predictions are concatenated without rewriting spectrum identifiers.

```bash
.venv-aichor/bin/aichor experiments submit local \
  --repo-dir . \
  --message "Run InstaNovo v1.2.2 ProteoBench sweep"
```

All run directories, predictions, per-run configs, logs, checksums, metric JSON, metric CSV, and submission comments are synced to `AICHOR_OUTPUT_PATH` when that environment variable is available.
