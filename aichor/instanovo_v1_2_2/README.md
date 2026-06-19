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

The smoke test uses the small InstaNovo-internal MGF requested for local wiring checks and skips ProteoBench metric computation by default.

```bash
python aichor/instanovo_v1_2_2/run_sweep.py \
  --smoke \
  --input-mgf /home/j-vangoey/code/InstaNovo-internal/data/small/small.mgf \
  --work-dir /tmp/proteobench-instanovo-smoke \
  --extra-override force_cpu=true \
  --extra-override fp16=false \
  --extra-override batch_size=4 \
  --extra-override num_workers=0
```

## Full Aichor Run

The full run downloads the ProteoBench De Novo DDA-HCD combined MGF by default. If multiple MGF files are supplied through `--input-dir`, each mode is run on every MGF and predictions are concatenated without rewriting spectrum identifiers.

```bash
.venv-aichor/bin/aichor experiments submit commit-sha "$(git rev-parse HEAD)" \
  --branch run-instanovo-v1.2.2-aichor \
  --manifest-path aichor/instanovo_v1_2_2/manifest.yaml
```

All run directories, predictions, per-run configs, logs, checksums, metric JSON, metric CSV, and submission comments are synced to `AICHOR_OUTPUT_PATH` when that environment variable is available.
