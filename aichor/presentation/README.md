# InstaNovo benchmarking deck

`python build_deck.py` → `index.html`. Open it directly; reveal.js is vendored in `vendor/`, so
there is no network dependency at presentation time.

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

That resolves the discrepancy this section used to describe as open. The conflicting chart's v1.3
figure (0.5772) matches our run under InstaNovo `Metrics` **exactly**; its v1.2.2 figure (0.5745)
matches neither of ours (0.5854 InstaNovo, 0.5883 ProteoBench). **Its v1.2.2 baseline is a
different run, not a different metric** — identifying which run remains open. An earlier version
of this README blamed the metric; that was wrong.

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
