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

## The one thing "just update the checkpoints" does not cover

**No released `instanovo` can load these checkpoints.** PyPI tops out at **1.2.2** (versions:
0.1.7, 1.0.0, 1.1.0–1.1.4, 1.2.2 — there is no 1.3.x), and these are internal training
artefacts with a **133-residue vocabulary**. The v1.2.2 image pinned `instanovo==1.2.2` from
PyPI; that pin would build cleanly here and then fail at checkpoint load.

So `INSTANOVO_INSTALL_SPEC` has **no default** and the build fails immediately while it is
empty. That is deliberate: failing at build is better than failing 20 minutes into a GPU run.
Supply one of:

```
# preferred: a wheel built from the internal repo, staged on the inputs bucket.
# No credentials in the manifest, and pinned by commit sha.
INSTANOVO_INSTALL_SPEC: "https://<inputs-bucket>/wheels/instanovo-1.3.0.dev0+<sha>-py3-none-any.whl"

# alternative, if the build can carry a token as a secret
INSTANOVO_INSTALL_SPEC: "instanovo @ git+https://<token>@github.com/instadeepai/InstaNovo-internal.git@<sha>"
```

Whichever is used, **record the commit sha** — it is part of what produced the numbers, and
unlike a PyPI version it is not recoverable from the image afterwards.

Two related consequences of moving off 1.2.2:

- **The torch upper bound is gone.** `torch<2.6` existed because torch ≥ 2.6's restricted
  unpickler refuses `SETITEM` on the defaultdict inside the 1.2.x checkpoints. The v1.3
  checkpoints were written by **torch 2.8.0+cu126** (see the logs of internal experiment
  `4cc23918`), so pinning below 2.6 would likely fail to load them.
- **`HOSTED_PLATFORM_MARKERS` stripping is probably now unnecessary.** `run_sweep.py` strips
  `AICHOR_LOGS_PATH` because instanovo 1.2.2 only accepted the S3 endpoint as `S3_ENDPOINT`;
  later versions read `AWS_ENDPOINT_URL`, which the platform sets. Harmless if left, but worth
  deleting once the install spec is settled — the code comment already says so.

## Running

```bash
./aichor/instanovo_v1_3_0/manifests/use.sh greedy    # copies to the root manifest.yaml
# fill in INSTANOVO_INSTALL_SPEC in manifest.yaml
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
