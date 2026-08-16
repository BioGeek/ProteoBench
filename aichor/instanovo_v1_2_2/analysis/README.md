# Analyses of the InstaNovo v1.2.2 ProteoBench sweep

Everything here runs on data the sweep already produced. No GPU, no re-inference — the
scored `intermediate.csv` files, the beam predictions, and the Winnow outputs are enough.

Each script re-derives a published figure as a check, so a broken extraction or a wrong
join shows up immediately rather than silently changing a conclusion:

| script | self-check |
|---|---|
| `mode_comparison.py` | the seven per-mode precisions must match the submitted table |
| `oracle_beams.py` | beam 0 must reproduce `exact=0.4222`, `exact+IL=0.7068` |
| `winnow_analysis.py` | accepted-set correctness must match the 90.60% behind the sTECE result |

## Setup

The scripts need only `pandas` and `numpy`. Every invocation below uses `uv` so nothing
has to be installed into the environment:

```bash
export AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=...
export AWS_ENDPOINT_URL=<object storage endpoint>     # AIchor exports this in-pod
RUN="uv run --no-project --with pandas --with numpy python"
```

## 1. Extract

Pulls only the needed columns, streaming each source rather than downloading it. The
sources total roughly 20GB; what lands is about 600MB.

```bash
./extract.sh ~/analysis-scratch
```

The AIchor experiment output paths are hard-coded in `extract.sh` — they identify
specific runs and cannot be derived, so they are listed there to keep the extraction
reproducible.

## 2. Compare the modes

Per-species performance, complementarity, what makes a spectrum hard, and the mammalian
refinement penalty.

```bash
$RUN mode_comparison.py ~/analysis-scratch
```

Produces the per-species table, the union-of-all-seven ensemble ceiling, the
uniquely-solved counts per mode, the difficulty breakdown by number of modes correct,
and the refinement gain split by peptide length and mammal/non-mammal.

## 3. Oracle beam ceiling

How often the ground truth is anywhere in the 10-beam list — the bound on any reranker.

```bash
aws --endpoint-url "$AWS_ENDPOINT_URL" s3 cp \
    "s3://dtu-denovo-s-2e6da747d6d34f62-outputs/output/e3543482-6b63-4467-87ac-868cddd7ae04/instanovo_v1_2_2_metrics/runs/beam10/raw_predictions.csv" - \
  | $RUN oracle_beams.py ~/analysis-scratch/gt_beam10.csv /dev/stdin
```

The 3.3GB predictions file is piped rather than stored. Reports the hit rate at each rank
and the oracle over all ten, at both exact and exact+IL level.

## 4. Winnow scores

Whether recalibration improves the *ranking* (as opposed to the calibration), how
over-confidence varies by species, and which features carry the signal.

```bash
$RUN winnow_analysis.py ~/analysis-scratch
```

## 5. Should refinement be gated?

Refinement helps overall but hurts mammals and long peptides. This evaluates per-spectrum
rules for when to apply it, using outcomes both models already produced -- no new inference.

```bash
$RUN refinement_gating.py ~/analysis-scratch
```

Rules are split into deployable ones (using only what is known at inference: the predicted
peptide, the model's log-probability, the organism sampled) and bounds marked `[bound]`
that read the ground truth and say what a rule built on that quantity could reach.

## 6. Learn when refinement helps

The hand-written gates in step 5 capture little of what is available. This trains a
classifier on the ~2% of spectra where refinement changes the outcome, and gates on it.

```bash
uv run --no-project --with pandas --with numpy --with scikit-learn python \
    refinement_predictor.py ~/analysis-scratch
```

Trains on five species and evaluates on four held out, so the reported gain is
cross-organism. Features are restricted to what is knowable at inference.

## 7. Repeatability as an abstention signal

The stochastic modes give a different answer on repeated runs. This asks whether that
disagreement predicts incorrectness, which would make it a quality filter needing no
labels and no model change.

```bash
$RUN stability.py ~/analysis-scratch diffusion_only
$RUN stability.py ~/analysis-scratch greedy_refined
```

Needs the replicate extracts (`rep_<mode>_rep{1,2,3}.csv`) alongside the primary run.

## 8. Modification disagreements

Spectra where every mode is wrong, all agree on the same peptide, and that peptide has an
identical backbone to the label — so only the modification state differs.

```bash
$RUN ptm_disagreements.py ~/analysis-scratch
```

Writes `ptm_disagreements.csv` alongside the extracts.

## Reading the output

Two limitations are worth carrying into any conclusion drawn from these scripts.

**The modes are not independent decoders.** All seven are the same two models — the
InstaNovo transformer and InstaNovo+ — under different search strategies. Agreement
between them reflects shared bias, not independent corroboration. This matters most in
`ptm_disagreements.py`, where unanimity is doing evidentiary work.

**Winnow's outputs cover only the FDR-accepted rows.** `winnow predict` writes the
accepted set, not everything it scored, so any AUC computed from them is truncated and
not comparable with a full-coverage figure. The subset is also selected by thresholding
the calibrated score, which biases comparisons in that score's favour.
