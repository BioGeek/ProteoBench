#!/usr/bin/env bash
# Calibration diagnostics for one InstaNovo inference mode, against the in-pod Koina.
#
# Inputs are pulled from object storage; results are written back next to them. The
# benchmark MGF carries SEQ= per spectrum, so winnow reads ground-truth labels straight
# from the spectra and no separate ground-truth join is needed.
#
# Usage: run_calibration.sh <mode> <predictions-s3-uri> <spectra-s3-uri> <output-s3-prefix>
set -euo pipefail

MODE="${1:?mode name, e.g. beam10}"
PREDICTIONS_URI="${2:?s3:// URI of raw_predictions.csv}"
SPECTRA_URI="${3:?s3:// URI of the benchmark MGF}"
OUTPUT_PREFIX="${4:?s3:// prefix to write results to}"

WORK_DIR="${WORK_DIR:-/tmp/winnow_${MODE}}"
mkdir -p "$WORK_DIR/data" "$WORK_DIR/results"

# The AWS CLI installed here is v1, which has no AWS_ENDPOINT_URL support, so the
# object-storage endpoint has to be passed explicitly. Whitespace is stripped because
# the value can arrive padded, which is silently fatal otherwise.
S3_ENDPOINT="$(printf '%s' "${AWS_ENDPOINT_URL:-${AWS_ENDPOINT_URL_S3:-${S3_ENDPOINT:-}}}" | tr -d '[:space:]')"
if [ -z "$S3_ENDPOINT" ]; then
    echo "[run_calibration] no S3 endpoint in AWS_ENDPOINT_URL / AWS_ENDPOINT_URL_S3 / S3_ENDPOINT" >&2
    exit 1
fi
echo "[run_calibration] using S3 endpoint: $S3_ENDPOINT"
aws_s3() { aws --endpoint-url "$S3_ENDPOINT" s3 "$@"; }

# The in-pod Triton speaks gRPC on 8500; TLS is for the public server only.
KOINA_SERVER_URL="${KOINA_SERVER_URL:-localhost:8500}"
KOINA_SSL="${KOINA_SSL:-false}"

# The nine-species MGF records no collision energy or fragmentation type, so the
# fragment-match features are computed against constants rather than per-row metadata.
# HCD is correct for this benchmark; the collision energy is a single assumed value
# standing in for spectra pooled from several labs, which weakens that feature.
COLLISION_ENERGY="${COLLISION_ENERGY:-27}"
FRAGMENTATION_TYPE="${FRAGMENTATION_TYPE:-HCD}"

# The spectrum file's own name is load-bearing: winnow derives spectrum_id as
# "<file stem>:<scan_number>" and joins predictions on it, so renaming the MGF on the
# way in silently breaks the join against InstaNovo's "<experiment_name>:<scan>" ids.
SPECTRA_FILENAME="$(basename "$SPECTRA_URI")"

echo "[run_calibration] fetching inputs for $MODE"
aws_s3 cp "$PREDICTIONS_URI" "$WORK_DIR/data/predictions.csv"
aws_s3 cp "$SPECTRA_URI" "$WORK_DIR/data/$SPECTRA_FILENAME"

echo "[run_calibration] diagnosing calibration for $MODE"
WINNOW_CONFIG_DIR="${WINNOW_CONFIG_DIR:-/opt/winnow-configs}"

winnow diagnose-calibration \
    --config-dir "$WINNOW_CONFIG_DIR" \
    diagnostics.label_source=sequence \
    dataset.spectrum_path_or_directory="$WORK_DIR/data/$SPECTRA_FILENAME" \
    dataset.predictions_path="$WORK_DIR/data/predictions.csv" \
    data_loader=instanovo \
    koina.server_url="$KOINA_SERVER_URL" \
    koina.ssl="$KOINA_SSL" \
    koina.input_constants.collision_energies="$COLLISION_ENERGY" \
    koina.input_constants.fragmentation_types="$FRAGMENTATION_TYPE" \
    2>&1 | tee "$WORK_DIR/results/diagnose_${MODE}.log"

echo "[run_calibration] uploading results for $MODE"
aws_s3 cp "$WORK_DIR/results/" "${OUTPUT_PREFIX%/}/$MODE/" --recursive

echo "[run_calibration] done: ${OUTPUT_PREFIX%/}/$MODE/"
