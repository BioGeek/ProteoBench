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
| Built from | `InstaNovo-internal` `test/v1-3-133res-inference` @ **`fdd7c7d3300b`**, clean tree |
| Wheel | `instanovo-1.3.0-py3-none-any.whl`, 200 KB, pure Python |
| sha256 | `b14569c108471cc01e164c7a400adbfcef0143563d13044d6627577c65c1b0b1` |
| Archived at | `s3://dtu-denovo-s-2e6da747d6d34f62-inputs/wheels/instanovo-1.3.0-fdd7c7d3300b/` |

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
internal branch in `fdd7c7d3300b` by adding `configs/**/*.yaml`; the wheel now ships **44**
config files, including all fourteen `v1_3_133res_*` inference configs.

### Where the 133 residues live, and why they are not in this wheel

The 133-residue set **is** a config file — `instanovo/configs/residues/extended.yaml`, whose
own header calls it "the residue set the v1.3.0 pretrained transformer checkpoint was trained
on". But it lives on the **training** branch `train-instanovoplus-1-3-133`, not on
`test/v1-3-133res-inference`, so it is absent from this wheel. The inference branch's residues
group holds 32 (`default`), 104 (`pride_extended`) and 5 (`unit_test`) entries.

It is selected as a Hydra override at training time, in `aichor_manifests/instanovoplus_4gpu.yaml`:

```
instanovo/cli.py diffusion train residues=extended dataset=extended_v13 model.vocab_size=136
```

(133 residues + PAD/SOS/EOS = 136.) **Inference resolves the vocabulary from the checkpoint
instead**, which is why its absence is not a problem here: internal runs `4cc23918` (greedy),
`3f3b282e` (knapsack beam-5) and `9aeb6891` (greedy + refinement, so InstaNovo+ as well) all
loaded these checkpoints with exactly this code and no `extended.yaml` present.

What the inference branch contributes is the inference-side handling —
`v1_3_133res_common.yaml`'s 35-entry `suppressed_residues` list and 7 extra `residue_remapping`
entries — and those *are* in the wheel.

**When this wheel would need rebuilding:** any run that passes `residues=extended` explicitly,
because the group would not resolve. That is not the sweep, but `extended.yaml` says it was
"generated to EXACTLY match the v2 extended vocab … for a fair v1.3-vs-v2 comparison", so a
planned v1.3-vs-v2 run is exactly the case that would need a wheel built from a branch carrying
it — either `train-instanovoplus-1-3-133` or the file cherry-picked onto the inference branch.

### Two consequences of leaving 1.2.2 behind

- **The torch upper bound is gone.** `torch<2.6` existed because torch ≥ 2.6's restricted
  unpickler refuses `SETITEM` on the defaultdict inside the 1.2.x checkpoints. The v1.3
  checkpoints were written by **torch 2.8.0+cu126** (see the logs of internal experiment
  `4cc23918`), so pinning below 2.6 would likely fail to load them.
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
