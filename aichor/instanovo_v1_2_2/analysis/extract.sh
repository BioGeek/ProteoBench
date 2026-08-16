#!/usr/bin/env bash
# Pull the columns the analyses need out of the scored runs, without landing the sources.
#
# Each mode's intermediate.csv is ~1.4GB and the Winnow feature matrix is ~5.2GB, so every
# fetch here streams the object and keeps only the handful of columns that matter. Nothing
# larger than ~150MB is written.
#
# Usage: extract.sh <output-dir>
set -euo pipefail

OUT="${1:?output directory}"
mkdir -p "$OUT"

BUCKET="${BUCKET:-dtu-denovo-s-2e6da747d6d34f62-outputs}"
# CLI v1 has no AWS_ENDPOINT_URL support, and the value can arrive whitespace-padded.
S3_ENDPOINT="$(printf '%s' "${AWS_ENDPOINT_URL:-${AWS_ENDPOINT_URL_S3:-${S3_ENDPOINT:-}}}" | tr -d '[:space:]')"
: "${S3_ENDPOINT:?set AWS_ENDPOINT_URL to the object-storage endpoint}"
s3_stream() { aws --endpoint-url "$S3_ENDPOINT" s3 cp "s3://$BUCKET/$1" - 2>/dev/null; }
PY="uv run --no-project --with pandas python"

# Each run's scored output. The paths are AIchor experiment outputs, so they are fixed
# per run rather than derivable; they are listed here so the extraction is reproducible.
BEAM10_INTERMEDIATE="output/e3543482-6b63-4467-87ac-868cddd7ae04/instanovo_v1_2_2_metrics/runs/beam10/intermediate.csv"
BEAM10_PREDICTIONS="output/e3543482-6b63-4467-87ac-868cddd7ae04/instanovo_v1_2_2_metrics/runs/beam10/raw_predictions.csv"
WINNOW_METADATA="output/winnow_predict/beam10/predictions/metadata.csv"
WINNOW_PREDS="output/winnow_predict/beam10/predictions/preds_and_fdr_metrics.csv"

MODES="
greedy output/8b794fca-7218-4659-bc18-251bfde58a52/instanovo_v1_2_2_metrics/runs/greedy/intermediate.csv
greedy_refined output/0c4467e7-c43a-4fe6-9a86-e44d8bc3552c/instanovo_v1_2_2_metrics/runs/greedy_refined/intermediate.csv
beam10_refined output/b1047c55-5075-413f-b8e6-19e53b1ff2a2/instanovo_v1_2_2_metrics/runs/beam10_refined/intermediate.csv
knapsack_beam10 output/4670d80d-a3e8-4998-a97e-63eb6a933cb8/instanovo_v1_2_2_metrics/runs/knapsack_beam10/intermediate.csv
knapsack_beam10_refined output/42638121-f931-49d1-b16f-81fb3abeda30/instanovo_v1_2_2_metrics/runs/knapsack_beam10_refined/intermediate.csv
diffusion_only output/013f843b-2624-4a80-8cee-ccaacc1a0342/instanovo_v1_2_2_diffusion_only/runs/diffusion_only/intermediate.csv
"

echo "[extract] ground truth, species and labels (from beam10)"
s3_stream "$BEAM10_INTERMEDIATE" | $PY -c "
import sys, pandas as pd
cols=['spectrum_id','peptidoform_ground_truth','collection','match_type','match_type_il','category']
pd.concat(list(pd.read_csv(sys.stdin, usecols=cols, chunksize=200000, low_memory=False))).to_csv('$OUT/gt_beam10.csv', index=False)
"

echo "[extract] spectrum-quality and modification columns (identical across modes)"
s3_stream "$BEAM10_INTERMEDIATE" | $PY -c "
import sys, pandas as pd
cols=['spectrum_id','peptide_length','missing_frag_pct','explained_all_pct','explained_by_pct',
      'cos','spec_pearson','precursor_mz','M-Oxidation','Q-Deamidation','N-Deamidation',
      'N-term Acetylation','N-term Carbamylation','N-term Ammonia-loss',
      'M-Oxidation (denovo)','Q-Deamidation (denovo)','N-Deamidation (denovo)',
      'N-term Acetylation (denovo)','N-term Carbamylation (denovo)','N-term Ammonia-loss (denovo)']
pd.concat(list(pd.read_csv(sys.stdin, usecols=cols, chunksize=200000, low_memory=False))).to_csv('$OUT/spectrum_features.csv', index=False)
"

echo "[extract] per-spectrum outcomes for the other six modes"
printf '%s\n' "$MODES" | while read -r mode key; do
    [ -z "$mode" ] && continue
    [ -f "$OUT/mode_$mode.csv" ] && { echo "  $mode already present"; continue; }
    s3_stream "$key" < /dev/null | $PY -c "
import sys, pandas as pd
cols=['spectrum_id','match_type','match_type_il','category','peptidoform']
d=pd.concat(list(pd.read_csv(sys.stdin, usecols=cols, chunksize=200000, low_memory=False)))
d.to_csv('$OUT/mode_$mode.csv', index=False)
print('  $mode:', f'{len(d):,}', 'rows')
"
done

echo "[extract] Winnow per-PSM scores and feature matrix"
s3_stream "$WINNOW_PREDS" | $PY -c "
import sys, pandas as pd
pd.concat(list(pd.read_csv(sys.stdin, usecols=['spectrum_id','calibrated_confidence','correct'], chunksize=200000))).to_csv('$OUT/winnow_preds.csv', index=False)
"
s3_stream "$WINNOW_METADATA" | $PY -c "
import sys, pandas as pd
cols=['spectrum_id','precursor_charge','longest_b_series','longest_y_series','complementary_ion_count',
      'max_ion_gap','b_y_intensity_ratio','spectral_angle','xcorr','irt_error','margin','median_margin',
      'entropy','z-score','edit_distance','min_token_probability','std_token_probability','mass_error_da']
pd.concat(list(pd.read_csv(sys.stdin, usecols=cols, chunksize=100000, low_memory=False))).to_csv('$OUT/winnow_features.csv', index=False)
"

echo "[extract] InstaNovo log-probabilities, for the ranking comparison"
s3_stream "$BEAM10_PREDICTIONS" | $PY -c "
import sys, pandas as pd
pd.concat(list(pd.read_csv(sys.stdin, usecols=['spectrum_id','scan_number','log_probs'], chunksize=250000, low_memory=False))).to_csv('$OUT/logprobs_beam10.csv', index=False)
"

echo "[extract] done -> $OUT"
du -sh "$OUT"
