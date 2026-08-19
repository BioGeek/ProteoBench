# InstaNovo benchmarking deck

`python build_deck.py` → `index.html`. **A single self-contained file**: reveal.js's CSS and JS are
inlined at build time, so `index.html` can be shared or emailed on its own — no `vendor/` directory
beside it, and no network access when viewed.

`vendor/` is kept as the provenance of those inlines (reveal.js 5.1.0) and is what `build_deck.py`
reads. Two details make the inlining safe: `reveal.css` references only `data:` URIs, and
`white.css`'s `@import url(./fonts/source-sans-pro/…)` is stripped, since those font files are not
vendored and the import could only 404 — the deck sets its own system font stack anyway. The build
checks that neither asset contains a literal `</script>` or `</style>` that would terminate the
document early.

Data-driven by design: runs are still landing, so updating the deck means editing the data tables
at the top of `build_deck.py` and regenerating, not editing slides.

## Where the numbers come from

| Block in `build_deck.py` | Source |
|---|---|
| `PB_V122` | Notion write-up section 1 — ProteoBench nine-species balanced, 779,879 spectra |
| `PB_V130_GREEDY` | `metrics_summary.csv` of experiment `9685299a` |
| `INTERNAL_V130` / `INTERNAL_V122` | pooled rows of `_scored/metrics.csv` and `_scored_knapsack/metrics.csv` |
| `PER_DATASET_GREEDY` | per-dataset rows of `_scored/metrics.csv`, `level=peptide evaluation=mass` |
| `WINNOW_*` | Notion sections 5, 15 and 26 |
| `STATUS` | live AIchor experiment states |

## Provenance captions

Every table and chart carries a `src()` caption **above** it naming the dataset, the spectrum count
where relevant, the checkpoint and the decoding mode. A reader landing on any single slide can tell
what it is about without inferring it from the heading, and a slide that mixes checkpoints (the
pooled internal table, the status matrices) says so explicitly rather than relying on a colour key.
The build asserts that no slide containing a table or chart lacks one.

## Status glyphs

The run matrices use shape-distinct text glyphs, ordered by pipeline stage:

| glyph | meaning |
|---|---|
| `○` | queued, not launched |
| `▸` | inference running |
| `⋯` | inference done, scoring |
| `✓` | scored — contributes a number to this deck |
| `✕` | deliberately not run |

Two stages matter because a run has to finish inference *and* be scored through ProteoBench's
scorer before it produces a comparable number, which is why `⋯` and `✓` are separate states.

An earlier version used `●` `◐` `◑` `○`, where the two in-progress states differed only in which
half of a circle was shaded — indistinguishable at slide size and carrying no meaning. The current
set differs in shape, so it survives greyscale, projection and colour-vision deficiency. All five
are plain text characters with broad font coverage; none is an emoji, so none brings its own colour
(`font-variant-emoji: text` guards the arrow against emoji presentation).

## Charts

Hand-built inline SVG rather than a plotting library, so the deck stays one self-contained file.

Palette is the validated categorical default: slot 1 blue `#2a78d6`/`#3987e5` for v1.2.2, slot 2
orange `#eb6834`/`#d95926` for v1.3.0, and the blue↔red diverging pair for the one chart that
encodes polarity (calibration gap by decile). Verified with the dataviz validator in both modes:

```
node scripts/validate_palette.js "#2a78d6,#eb6834,#1baf7a" --mode light --pairs all   # ALL PASS
node scripts/validate_palette.js "#3987e5,#d95926,#199e70" --mode dark                # ALL PASS
```

Both light and dark are selected — the dark values are their own steps against the dark surface,
not an automatic flip. Every chart carries direct value labels, so identity and magnitude never
depend on colour alone, and each mark has a `<title>` for hover.

## The two scorers, and the resolved discrepancy

InstaNovo's `Metrics` and ProteoBench's `DenovoScores` are different measurements: **50/20 ppm**
against **0.5/0.1 Da**, bidirectional prefix+suffix alignment against equal-length-all-matched,
and `precision = 1.0` on an empty prediction set. Identical in v1.2.2 and v1.3.0, so it is a
scorer difference rather than a version one.

Run over the same 17 prediction sets they agree to within **0.003** on the mean, with ProteoBench
marginally *looser* in 14 of 17 — the opposite of what the tolerance predicts, because the
bidirectional alignment offsets the tighter threshold. Both put the v1.3 checkpoint behind
(−0.82 pp and −1.02 pp).

That resolves the discrepancy this section used to describe as open, and the cause is now identified.
The chart was built in another session from a Google Sheets workbook: its v1.3 side is exactly our
runs `4cc23918` and `3f3b282e`, and its v1.2.2 side was copied from a tab named
**`instanovo_1_2_2_with_new_splits`** — a v1.2.2 evaluation on the **re-split** data.

The residual confirms it: −0.0186 mean on the nine `ninespecies` sets, which are split 80/10/10,
against −0.0022 on the eight biological sets, which are test-only and cannot be re-split
(`wound_fluids` matches to 0.0001). A re-split cannot move a set that was never split.

**Our matrix runs on `ninespecies_v1`**, via the `pipeline.yaml` both arms share, so the comparison
is internally consistent — one split, weights the only variable. That it is the *old* split is an
inference, not a direct observation: the workbook baseline is the one labelled "with new splits" and
our numbers differ from it exactly on the split-affected datasets. Where the new split physically
lives is unconfirmed; `ninespecies_v2` appears in one script and in no run or config.

Two earlier explanations, both wrong and both recorded so they are not re-derived: the metric
(scorers agree to 0.003) and a differing checkpoint (the residual is split-shaped, not
checkpoint-shaped).

Also never compare `pep_recall_at_0.050_fdr` against either headline: it is a third quantity
(clambacteria 0.153 against 0.472 unfiltered).

## Superseded: the discrepancy as first written

An existing chart of the same comparison (v1.2.2 vs v1.3.0 peptide recall, per dataset, faceted by
decoding mode) reports **greedy means 0.5745 → 0.5772, +0.27 pp with v1.3.0 ahead**.

Scoring the same runs through ProteoBench's scorer gives **0.5883 → 0.5781, −1.02 pp with v1.3.0
behind**, ahead in only 5 of 17 datasets. Six datasets carry the opposite sign:

| dataset | other chart | `_scored/metrics.csv` |
|---|---|---|
| yeast | +2.2 | −1.7 |
| mmazei | +1.6 | −0.3 |
| tomato | +1.1 | −0.9 |
| bacillus | +1.1 | −1.0 |
| ricebean | +0.1 | −2.4 |
| clambacteria | +1.4 | +0.2 |
| herceptin | +7.8 | +7.2 |
| woundfluids | −4.1 | −4.1 |

Ruled out as the explanation:

- **Not weighting.** Spectrum-weighted pooling moves our figure further from the other chart
  (0.6031 → 0.5852), not closer.
- **Not the internal harness metric.** The harness's own per-dataset `pep_recall` from
  `instanovo_results.csv` gives a v1.2.2 greedy mean of 0.5854 and still puts yeast negative
  (0.6346 → 0.6203), so it does not reproduce the other chart either.

The two are therefore not the same quantity, and the direction of the headline depends on which is
used. **The other chart's metric source needs identifying before either version is shown.** The deck
presents the ProteoBench-scored version and states the conflict on the slide rather than picking a
side silently.

## Extending to all variants

The per-dataset slide currently shows the greedy facet only, because that is the one mode pair where
both checkpoints have been scored. Adding facets is a matter of adding entries to
`PER_DATASET_GREEDY`-style tables once the consolidated scoring job finishes — it covers eight runs
including both beam-5 arms. Pairs that will never exist should stay absent rather than blank:
`v1_2_2_test_knapsack_beam5` was deliberately not launched, so there is no v1.2.2 counterpart for the
knapsack facet on the internal sets.

## Checking the layout

`tools/check_layout.sh [WIDTH,HEIGHT]` renders the deck in headless Chrome and reports layout
defects. Run it after any content edit; the deck is written by hand and the failures below were all
introduced by adding prose, not by the tooling.

Three passes, because the first one alone gave a false all-clear:

| pass | what it catches |
|------|-----------------|
| `fit` | Slides spilling past the window, and slides that only fit by rendering small |
| `overlap` | Two chart labels on top of each other; any label drawn outside its `viewBox` |
| `geometry` | A label sitting on a data marker, or struck through by a connector line |

**Why three.** A section-relative overflow check reports nothing, ever: reveal.js *grows* a section
to fit its content, so the content never overflows the section — it overflows the **window**, because
reveal only ever computes its scale for the authored 1280×800. Eight slides were spilling up to
531px below the fold while a naive check called them clean. The `fit` pass measures against the
viewport instead.

The deck now also shrinks to fit: on `slidechanged` it tells reveal the slide is as tall as its
content actually is, and reveal's own `min(availW/width, availH/height)` scale does the rest. That
makes spill impossible, so `fit` additionally reports each slide's scale as a fraction of the deck
baseline — a slide that "fits" at 46% of normal type size is not fixed, it is hidden. Below ~0.88 the
content needs cutting.

`overlap` and `geometry` exist because neither is visible to a height measurement. A dashed trend
line running through a point label, or a label resting on its own marker, is exactly as broken as
text off the edge, and both were present on the cost scatter.

**On the `fit` floor.** `FIT_FLOOR` in `tools/report.py` is 0.82, and it is calibrated against renders
rather than chosen a priori: the failure that motivated this check was a slide fitting at **0.46** with
531px off-screen, and slides at 0.84 read comfortably at presentation size. It started at 0.88 and was
lowered once, deliberately — at 0.88 it fired on two slides that a screenshot showed were perfectly
legible, and the only way to satisfy it was deleting content that belonged there. A threshold that
gets satisfied by cutting substance is worse than the small type it was guarding against. Raise it
again if the deck's type ever gets genuinely hard to read; do not raise it and then trim prose to
match.

Grid lines are excluded from `geometry` — a label crossing a faint gridline is ordinary chart
practice, unlike one crossing a data point or a trend line.

## A limitation of the visual check

`tools/check_layout.sh` measures the live DOM and is trustworthy. **Headless screenshots of this deck
are not**, and the two disagree.

Chasing an apparent clipping bug in the refinement chart cost several rounds: screenshots showed row
labels truncated to `clambac`, one dataset label missing, and only 3 of 7 value labels drawn. Every
one of those elements was present and correctly sized in the DOM — an in-page probe reported 22 text
nodes, none zero-width, with sensible bounding boxes, while the rendered PNG omitted them. Two
screenshots at different `--virtual-time-budget` values were byte-identical, so it is deterministic
rather than a transition race, but it is a rendering artefact of the capture path and not a defect in
the page.

Consequence: **do not redesign a chart on the strength of a screenshot alone.** Check the generated
markup and the probe output first. A richer per-dataset version of the refinement chart was replaced
with the simpler pooled one partly on this bad evidence; the simpler chart is kept because it states
the headline adequately, not because the other was broken.
