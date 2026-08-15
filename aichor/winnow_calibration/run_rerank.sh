#!/usr/bin/env bash
# Rerank one InstaNovo beam-search mode by calibrated confidence.
#
# Winnow scores whichever prediction a row presents as top-1, so each beam is presented
# as the top-1 in turn, scored, and the highest-scoring candidate kept per spectrum.
# Unlike rescoring, this can change the predicted peptide, and so precision and recall.
#
# Cost scales with the beam count: every beam is a full scoring pass, including
# re-parsing the spectrum file. Set MAX_BEAMS to sample fewer.
#
# Usage: run_rerank.sh <mode> <predictions-s3-uri> <spectra-s3-uri> <output-s3-prefix>
set -euo pipefail

MODE="${1:?mode name, e.g. beam10}"
PREDICTIONS_URI="${2:?s3:// URI of raw_predictions.csv}"
SPECTRA_URI="${3:?s3:// URI of the benchmark MGF}"
OUTPUT_PREFIX="${4:?s3:// prefix to write results to}"

WORK_DIR="${WORK_DIR:-/tmp/winnow_rerank_${MODE}}"
mkdir -p "$WORK_DIR/data" "$WORK_DIR/candidates" "$WORK_DIR/scored" "$WORK_DIR/results"

S3_ENDPOINT="$(printf '%s' "${AWS_ENDPOINT_URL:-${AWS_ENDPOINT_URL_S3:-${S3_ENDPOINT:-}}}" | tr -d '[:space:]')"
if [ -z "$S3_ENDPOINT" ]; then
    echo "[run_rerank] no S3 endpoint in AWS_ENDPOINT_URL / AWS_ENDPOINT_URL_S3 / S3_ENDPOINT" >&2
    exit 1
fi
aws_s3() { aws --endpoint-url "$S3_ENDPOINT" s3 "$@"; }

KOINA_SERVER_URL="${KOINA_SERVER_URL:-localhost:8500}"
KOINA_SSL="${KOINA_SSL:-false}"
COLLISION_ENERGY="${COLLISION_ENERGY:-27}"
FRAGMENTATION_TYPE="${FRAGMENTATION_TYPE:-HCD}"
WINNOW_CONFIG_DIR="${WINNOW_CONFIG_DIR:-/opt/winnow-configs}"
FDR_THRESHOLD="${FDR_THRESHOLD:-0.05}"
CONFIDENCE_COLUMN="${CONFIDENCE_COLUMN:-calibrated_confidence}"
MAX_BEAMS="${MAX_BEAMS:-}"

SPECTRA_FILENAME="$(basename "$SPECTRA_URI")"

echo "[run_rerank] fetching inputs for $MODE"
aws_s3 cp "$PREDICTIONS_URI" "$WORK_DIR/data/predictions.csv"
aws_s3 cp "$SPECTRA_URI" "$WORK_DIR/data/$SPECTRA_FILENAME"

# Splitting first also verifies the tokeniser against InstaNovo's own output, so a
# mismatch stops the run before any scoring time is spent.
echo "[run_rerank] building per-beam candidates"
python /usr/local/bin/beam_candidates.py split \
    --predictions "$WORK_DIR/data/predictions.csv" \
    --output-dir "$WORK_DIR/candidates" \
    ${MAX_BEAMS:+--max-beams "$MAX_BEAMS"} \
    2>&1 | tee "$WORK_DIR/results/split_${MODE}.log"

for candidate in "$WORK_DIR"/candidates/beam_*.csv; do
    beam="$(basename "$candidate" .csv)"
    echo "[run_rerank] scoring $beam"
    winnow predict \
        --config-dir "$WINNOW_CONFIG_DIR" \
        dataset.spectrum_path_or_directory="$WORK_DIR/data/$SPECTRA_FILENAME" \
        dataset.predictions_path="$candidate" \
        data_loader=instanovo \
        koina.server_url="$KOINA_SERVER_URL" \
        koina.ssl="$KOINA_SSL" \
        koina.input_constants.collision_energies="$COLLISION_ENERGY" \
        koina.input_constants.fragmentation_types="$FRAGMENTATION_TYPE" \
        fdr_control.fdr_threshold="$FDR_THRESHOLD" \
        output_folder="$WORK_DIR/scored/$beam" \
        2>&1 | tee "$WORK_DIR/results/predict_${beam}.log"

    # Keep each beam's scores as they land, so a later failure does not cost the earlier ones.
    aws_s3 cp "$WORK_DIR/scored/$beam/" "${OUTPUT_PREFIX%/}/$MODE/scored/$beam/" --recursive
done

echo "[run_rerank] choosing the winning candidate per spectrum"
python /usr/local/bin/beam_candidates.py combine \
    --scored-dir "$WORK_DIR/scored" \
    --output "$WORK_DIR/results/reranked_${MODE}.csv" \
    --confidence-column "$CONFIDENCE_COLUMN" \
    2>&1 | tee "$WORK_DIR/results/combine_${MODE}.log"

echo "[run_rerank] uploading results for $MODE"
aws_s3 cp "$WORK_DIR/results/" "${OUTPUT_PREFIX%/}/$MODE/" --recursive

echo "[run_rerank] done: ${OUTPUT_PREFIX%/}/$MODE/"
