#!/usr/bin/env bash
# Rescore one InstaNovo inference mode: calibrated confidence and FDR control for the
# model's own top-1 prediction. The peptides are unchanged; only the score is new.
#
# Usage: run_predict.sh <mode> <predictions-s3-uri> <spectra-s3-uri> <output-s3-prefix>
set -euo pipefail

MODE="${1:?mode name, e.g. beam10}"
PREDICTIONS_URI="${2:?s3:// URI of raw_predictions.csv}"
SPECTRA_URI="${3:?s3:// URI of the benchmark MGF}"
OUTPUT_PREFIX="${4:?s3:// prefix to write results to}"

WORK_DIR="${WORK_DIR:-/tmp/winnow_predict_${MODE}}"
mkdir -p "$WORK_DIR/data" "$WORK_DIR/results"

# The AWS CLI here is v1, which has no AWS_ENDPOINT_URL support, so the endpoint is
# passed explicitly. Whitespace is stripped because the value can arrive padded.
S3_ENDPOINT="$(printf '%s' "${AWS_ENDPOINT_URL:-${AWS_ENDPOINT_URL_S3:-${S3_ENDPOINT:-}}}" | tr -d '[:space:]')"
if [ -z "$S3_ENDPOINT" ]; then
    echo "[run_predict] no S3 endpoint in AWS_ENDPOINT_URL / AWS_ENDPOINT_URL_S3 / S3_ENDPOINT" >&2
    exit 1
fi
aws_s3() { aws --endpoint-url "$S3_ENDPOINT" s3 "$@"; }

KOINA_SERVER_URL="${KOINA_SERVER_URL:-localhost:8500}"
KOINA_SSL="${KOINA_SSL:-false}"
COLLISION_ENERGY="${COLLISION_ENERGY:-27}"
FRAGMENTATION_TYPE="${FRAGMENTATION_TYPE:-HCD}"
WINNOW_CONFIG_DIR="${WINNOW_CONFIG_DIR:-/opt/winnow-configs}"
FDR_THRESHOLD="${FDR_THRESHOLD:-0.05}"

# Winnow derives spectrum_id from the spectrum file's own stem, so the name must survive.
SPECTRA_FILENAME="$(basename "$SPECTRA_URI")"

echo "[run_predict] fetching inputs for $MODE"
aws_s3 cp "$PREDICTIONS_URI" "$WORK_DIR/data/predictions.csv"
aws_s3 cp "$SPECTRA_URI" "$WORK_DIR/data/$SPECTRA_FILENAME"

echo "[run_predict] rescoring $MODE"
winnow predict \
    --config-dir "$WINNOW_CONFIG_DIR" \
    dataset.spectrum_path_or_directory="$WORK_DIR/data/$SPECTRA_FILENAME" \
    dataset.predictions_path="$WORK_DIR/data/predictions.csv" \
    data_loader=instanovo \
    koina.server_url="$KOINA_SERVER_URL" \
    koina.ssl="$KOINA_SSL" \
    koina.input_constants.collision_energies="$COLLISION_ENERGY" \
    koina.input_constants.fragmentation_types="$FRAGMENTATION_TYPE" \
    fdr_control.fdr_threshold="$FDR_THRESHOLD" \
    output_folder="$WORK_DIR/results/predictions" \
    2>&1 | tee "$WORK_DIR/results/predict_${MODE}.log"

echo "[run_predict] uploading results for $MODE"
aws_s3 cp "$WORK_DIR/results/" "${OUTPUT_PREFIX%/}/$MODE/" --recursive

echo "[run_predict] done: ${OUTPUT_PREFIX%/}/$MODE/"
