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

# The in-pod Triton speaks gRPC on 8500; TLS is for the public server only.
KOINA_SERVER_URL="${KOINA_SERVER_URL:-localhost:8500}"
KOINA_SSL="${KOINA_SSL:-false}"

# The nine-species MGF records no collision energy or fragmentation type, so the
# fragment-match features are computed against constants rather than per-row metadata.
# HCD is correct for this benchmark; the collision energy is a single assumed value
# standing in for spectra pooled from several labs, which weakens that feature.
COLLISION_ENERGY="${COLLISION_ENERGY:-27}"
FRAGMENTATION_TYPE="${FRAGMENTATION_TYPE:-HCD}"

echo "[run_calibration] fetching inputs for $MODE"
aws s3 cp "$PREDICTIONS_URI" "$WORK_DIR/data/predictions.csv"
aws s3 cp "$SPECTRA_URI" "$WORK_DIR/data/spectra.mgf"

echo "[run_calibration] diagnosing calibration for $MODE"
winnow diagnose-calibration \
    diagnostics.label_source=sequence \
    dataset.spectrum_path_or_directory="$WORK_DIR/data/spectra.mgf" \
    dataset.predictions_path="$WORK_DIR/data/predictions.csv" \
    dataset.data_loader=instanovo \
    koina.server_url="$KOINA_SERVER_URL" \
    koina.ssl="$KOINA_SSL" \
    koina.input_constants.collision_energies="$COLLISION_ENERGY" \
    koina.input_constants.fragmentation_types="$FRAGMENTATION_TYPE" \
    2>&1 | tee "$WORK_DIR/results/diagnose_${MODE}.log"

echo "[run_calibration] uploading results for $MODE"
aws s3 cp "$WORK_DIR/results/" "${OUTPUT_PREFIX%/}/$MODE/" --recursive

echo "[run_calibration] done: ${OUTPUT_PREFIX%/}/$MODE/"
