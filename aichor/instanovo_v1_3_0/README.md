# InstaNovo v1.3.0 on the ProteoBench nine-species balanced dataset

The seven decoding variants of the v1.2.2 sweep, re-run with the v1.3.0 checkpoints, on the
same dataset with the same settings. The point is a like-for-like checkpoint comparison: every
difference against the published v1.2.2 numbers should be attributable to the weights.

## What is identical to the v1.2.2 sweep

- **The dataset.** `run_sweep.py` defaults to
  `https://proteobench.cubimed.rub.de/raws/DeNovo-HCD/nine_species_balanced_De_Novo.mgf.gz`,
  and none of these manifests overrides it. This is the reprocessed nine-species set
  ([Scientific Data, 2024](https://www.nature.com/articles/s41597-024-04068-4)) — the "v2" in
  its informal name refers to that reprocessing, not to a different file.
- **The sweep implementation.** These manifests invoke `../instanovo_v1_2_2/run_sweep.py`
  rather than a copy. It already takes the checkpoints as flags, so a second copy would only
  be a second thing to keep in step. The directory name is historical; read it as "the sweep".
- **Beam widths, refinement gating, resources.** 10 beams where the v1.2.2 sweep used 10, the
  shipped `refine_all: false` / `refine_threshold: 0.9` gate, and the same worker shape
  (24 CPUs, ramRatio 8, one full `NVIDIA-H100-80GB-HBM3`).

## What changed

Only the checkpoints, passed per variant:

| Model | Checkpoint |
| --- | --- |
| Transformer | `s3://…/output/33768d55-ac95-40ab-9545-b3889ef8facf/checkpoints/instanovo-base/model_best.ckpt` |
| InstaNovo+ | `s3://…/output/8d0443f2-7524-41a8-b5db-037fa7fc2276/checkpoints/instanovoplus-base/model_best.ckpt` |

`--instanovo-plus-model` is passed only for the four variants that use it (the three refined
ones and `diffusion_only`); `--instanovo-model` only for the six that run the transformer.

## The instanovo build: a vendored wheel

**No released `instanovo` can load these checkpoints.** PyPI tops out at **1.2.2** (0.1.7,
1.0.0, 1.1.0–1.1.4, 1.2.2 — there is no 1.3.x), and these are internal training artefacts with
a 133-residue vocabulary. The v1.2.2 image pinned `instanovo==1.2.2` from PyPI; that pin would
build cleanly here and then fail at checkpoint load.

So the image installs a wheel built from the internal repo and vendored into `wheels/`:

| | |
| --- | --- |
| Built from | `InstaNovo-internal` `test/v1-3-133res-inference` @ **`03a876d414f0`**, clean tree |
| Wheel | `instanovo-1.3.0-py3-none-any.whl`, 200 KB, pure Python |
| sha256 | `6747cb796f8a49ceae1772edfb8f34d87c8646350ea326a1f05662ba35f7e1df` |
| Archived at | `s3://dtu-denovo-s-2e6da747d6d34f62-inputs/wheels/instanovo-1.3.0-03a876d414f0/` |
| Config files | 45, including `configs/residues/extended.yaml` (133 residues) |

It is **vendored rather than fetched from the bucket** because the install runs at *build* time
and the image build has no bucket credentials. The bucket copy is the canonical archive; the two
are identical by the checksum in `wheels/SHA256SUMS`, which the Dockerfile verifies with
`sha256sum -c` before installing. A 200 KB pure-Python wheel in git is a deliberate trade for a
build that needs no credentials and no network.

### One packaging bug had to be fixed first

A wheel built from that branch as it stood shipped **6** config files where the released 1.2.2
wheel ships **31**. `[tool.setuptools.package-data]` listed `configs/*.yaml`, which matches one
level only, so every config *group* was silently dropped — `inference/`, `residues/`,
`dataset/`, `model/`, `accelerate/`, `finetune/`. Such a wheel installs and imports cleanly and
then fails at run time when Hydra cannot find `configs/inference/default.yaml`. Fixed on the
internal branch in `fdd7c7d3300b` by adding `configs/**/*.yaml`; the wheel now ships **45**
config files, including all fourteen `v1_3_133res_*` inference configs.

### The 133-residue vocabulary is in the wheel

`instanovo/configs/residues/extended.yaml` — 133 residues, 136 with PAD/SOS/EOS, described by
its own header as "the residue set the v1.3.0 pretrained transformer checkpoint was trained
on" — originally existed only on the **training** branch `train-instanovoplus-1-3-133`. It has
been cherry-picked verbatim onto `test/v1-3-133res-inference`, so the wheel now carries it
alongside `default` (32), `pride_extended` (104) and `unit_test` (5).

**Strictly it is not needed for inference.** The vocabulary comes from the checkpoint, and
nothing in the inference config chain selects a residues group — which is why internal runs
`4cc23918` (greedy), `3f3b282e` (knapsack beam-5) and `9aeb6891` (greedy + refinement, so
InstaNovo+ too) all loaded these checkpoints from a tree without the file. It is included so
the artefact is self-describing, and so a run that *does* pass `residues=extended` resolves
rather than failing. `extended.yaml` says it was "generated to EXACTLY match the v2 extended
vocab … for a fair v1.3-vs-v2 comparison", and that comparison is exactly such a run.

For reference, the override at training time was:

```
instanovo/cli.py diffusion train residues=extended dataset=extended_v13 model.vocab_size=136
```

Note the file's own instruction to keep it in sync with the v2 copy at
`libs/instanovo-core/.../residues/extended.yaml`; this vendored wheel is now a third copy, so
treat the training branch as the source of truth if they ever diverge.

### Two consequences of leaving 1.2.2 behind

- **torch is pinned to `2.8.0`, not unbounded.** `torch<2.6` in the v1.2.2 image existed
  because torch ≥ 2.6's restricted unpickler refuses `SETITEM` on the defaultdict inside the
  checkpoints. That bound is wrong for v1.3, but unbounded is worse: the first launch resolved
  to **torch 2.13.0+cu130** and all seven runs died at checkpoint load with `Can only SETITEM
  for dict, collections.OrderedDict, collections.Counter, but got defaultdict` — even though
  `instanovo/transformer/model.py` registers `defaultdict` via `add_safe_globals`. Some torch
  after 2.8 tightened that check beyond what the allowlist covers. 2.8.0 is what the internal
  `cu126` extra pins and what runs `4cc23918`, `3f3b282e` and `9aeb6891` used, so it is the only
  version these checkpoints are known to load under.
- **`HOSTED_PLATFORM_MARKERS` stripping is probably now unnecessary.** `run_sweep.py` strips
  `AICHOR_LOGS_PATH` because instanovo 1.2.2 only accepted the S3 endpoint as `S3_ENDPOINT`;
  later versions read `AWS_ENDPOINT_URL`, which the platform sets. It is left in place because
  removing it would edit the shared `run_sweep.py` and change the v1.2.2 runs' behaviour too;
  the code comment already flags it as deletable. Worth checking on the first v1.3 run whether
  TensorBoard logging is silently disabled by the stripping.

## Running

```bash
./aichor/instanovo_v1_3_0/manifests/use.sh greedy    # copies to the root manifest.yaml
git commit -am "run: v1.3.0 greedy on nine-species balanced"
aichor experiments submit local --repo-dir . --message "v1.3.0 greedy"
```

Variants, cheapest first, with the v1.2.2 GPU time as the only available guide to cost:

| Variant | v1.2.2 GPU time |
| --- | --- |
| `greedy` | 1 h 30 m |
| `diffusion_only` | 2 h 48 m |
| `greedy_refined` | 2 h 53 m |
| `beam10` | 10 h 10 m |
| `beam10_refined` | 20 h 48 m |
| `knapsack_beam10` | 25 h 24 m |
| `knapsack_beam10_refined` | 35 h 50 m |

Those are v1.2.2 measurements, not predictions for v1.3. On the internal held-out sets the two
generations cost the same per spectrum at both greedy and beam-5, which is mild evidence they
will be close here too — but the knapsack ratio did **not** transfer between benchmarks there
(2.5× beam on ProteoBench against 7.2× internally), so treat the two knapsack rows as the
least trustworthy.

**The knapsack cache cannot be reused from the v1.2.2 runs.** It is derived from the residue
vocabulary, and v1.3 has a different one. Left to itself each knapsack run rebuilds its own
under `--work-dir`; pass `--knapsack-path` pointing at shared storage if you want the two
knapsack variants to share one.

## Scoring

`run_sweep.py --full` computes ProteoBench's metrics itself, against ProteoBench's ground
truth, exactly as it did for v1.2.2 — so the outputs are directly comparable with the numbers
in the benchmark write-up, and no separate scoring pass is needed.

The analysis scripts in `../instanovo_v1_2_2/analysis/` take a directory of scored results and
can be pointed at these outputs. One exception: `paired_stats.py` carries a `PUBLISHED` dict of
v1.2.2 numbers as a self-check, and that will need v1.3 values before it means anything here.
