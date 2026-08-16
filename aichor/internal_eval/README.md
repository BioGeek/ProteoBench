# Scoring internal held-out runs with ProteoBench's metrics

The InstaNovo internal evaluation harness reports `aa_prec`, `aa_recall` and `pep_recall` per
dataset. ProteoBench reports an exact/mass split, three ambiguity toggles on top of exact
matching (I/L, deamidation, both), and an area under the precision-vs-coverage curve. None of
the ProteoBench columns can be recovered from the internal ones, so "do the ProteoBench
conclusions hold on our test sets?" cannot be answered from the harness output as it stands.

`score_with_proteobench.py` closes that gap. It reads the per-dataset prediction CSVs a run
writes to `${output_dir}/${run_name}/samples/*.csv` and pushes them through the same
`DenovoScores` / `DenovoDatapoint` code path a ProteoBench submission goes through, using the
same column mapping as ProteoBench's own InstaNovo parser
(`proteobench/io/parsing/io_parse_settings/denovo/DDA/HCD/parse_settings_instanovo.toml`).

## Usage

```bash
# 1. pull a run's per-dataset predictions
aichor storage cloud download \
    --storage-id dtu-denovo-s-2e6da747d6d34f62-outputs \
    --remote-path evaluation/instanovo_v1_3_133res_test_greedy/samples/ \
    --local-path /scratch/greedy_v1_3/samples/

# 2. score them
python aichor/internal_eval/score_with_proteobench.py \
    /scratch/greedy_v1_3/samples \
    --out /scratch/greedy_v1_3/scored \
    --label greedy_v1_3 \
    --save-intermediate
```

Needs an environment with `proteobench` installed (`pip install -e '.[dev]'`), because it
imports the scorer rather than reimplementing it — that is the whole point.

## Outputs

`metrics.csv`, long format, one row per `dataset × level × evaluation × ambiguity`, plus a
pooled `__ALL__` row per combination:

| column | meaning |
|---|---|
| `run`, `dataset` | run label and dataset (`__ALL__` = pooled across datasets) |
| `level` | `peptide` or `aa` |
| `evaluation` | `mass` or `exact` |
| `ambiguity` | `""`, `il`, `deam`, `both` (only meaningful with `evaluation=exact`) |
| `precision`, `recall`, `coverage` | `c/ci`, `c/n`, `ci/n` |
| `auc` | area under the precision-vs-coverage curve |
| `n` | denominator (spectra, or ground-truth residues at `aa` level) |
| `aa_scores_broadcast` | **read this before comparing aa AUC** — see below |
| `unparseable_prediction` | predictions that would not parse as a peptidoform; kept as misses |

Pooled metrics re-derive the score and correctness vectors and rank them together, rather than
averaging per-dataset values. Averaging AUCs across datasets is not the AUC of the pooled
ranking, and the difference is not small when the datasets differ in difficulty.

With `--save-intermediate`, one parquet per dataset holds the per-spectrum match columns
(`spectrum_id`, `match_type`, `match_type_il`, `match_type_deam`, `match_type_both`, `score`,
`collection`, `category`), which is the input shape `paired_stats.py` and the other scripts in
`aichor/instanovo_v1_2_2/analysis/` expect.

## Things that will look like bugs and are not

**`aa_scores_broadcast=True` inflates amino-acid AUC.** When a run supplies no usable
per-token scores, ProteoBench broadcasts the peptide score across every residue. Ranking
residues then reduces to ranking peptides, which is an easier problem, so aa AUC rises
relative to a mode reporting genuine per-residue confidence. InstaNovo+ 1.2.2 declares but
never fills its per-token column, so **every refined mode hits this path**. Compare aa AUC
only between runs with the same `aa_scores_broadcast` value.

**Amino-acid `exact` can exceed amino-acid `mass`.** `aa_exact_dn` is positional character
equality with no mass alignment; `aa_matches_dn` is the mass-based prefix/suffix match. A
reversed prediction scores 1/13 exact and 0/13 mass. On datasets with many wrong answers the
exact rate therefore sits above the mass rate, inverting the ordering that holds at peptide
level.

**Amino-acid `coverage` can exceed 1.0.** Denominator counts ground-truth residues, numerator
counts predicted ones.

## Departures from the ProteoBench parser

Both are forced by the data, and both are in the script's module docstring:

- Spectrum IDs are kept as strings and prefixed with the dataset name. ProteoBench extracts a
  trailing integer scan ID, which is unique within its single benchmark file; internal IDs like
  `Peng2021_Herceptin_elastase:4135` are only unique within a dataset.
- `add_fasta_category` is disabled. It matches wrong answers against per-species peptide sets
  downloaded from the ProteoBench server, which describe the ProteoBench benchmark's species,
  not ours.

## Recommended first check

Before trusting a cross-benchmark comparison, run the adapter over the ProteoBench InstaNovo
prediction CSV for a mode we have already submitted, and confirm it reproduces that
submission's published `peptide/mass` precision. That exercises the frame construction against
a known answer; everything downstream of it is ProteoBench's own code.
