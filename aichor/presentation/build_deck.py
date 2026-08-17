"""Build the InstaNovo benchmarking reveal.js deck.

Data-driven on purpose: runs are still landing, so regenerating the deck is
`python build_deck.py` rather than hand-editing slides. Every number below is sourced
from the Notion write-up or a run's own metrics_summary; provenance is in the comments.

Charts are hand-built inline SVG rather than a plotting library so the deck stays a single
self-contained file with no network at presentation time. Palette is the validated
categorical default (slots 1-2 for the two checkpoints, blue/red diverging for the
calibration polarity chart), checked with the dataviz validator in both modes.
"""

from __future__ import annotations

import html
import pathlib

OUT = pathlib.Path(__file__).parent / "index.html"

# ── palette (validated: see the build notes in README.md) ───────────────────────────────
C_V122 = "var(--series-1)"  # blue   #2a78d6 / #3987e5
C_V130 = "var(--series-2)"  # orange #eb6834 / #d95926
C_MUTED = "var(--text-muted)"
C_GRID = "var(--grid)"
C_OVER = "var(--diverge-warm)"  # red  — over-confident
C_UNDER = "var(--diverge-cool)"  # blue — under-confident

# ── ProteoBench nine-species balanced, InstaNovo v1.2.2 (Notion section 1) ──────────────
# mode, pep/mass, pep/exact, exact+IL, aa/mass, pep AUC, GPU hours
PB_V122 = [
    ("greedy (1 beam)", 0.6946, 0.4045, 0.6749, 0.8335, 0.9177, 1.50),
    ("beam search (10)", 0.7278, 0.4222, 0.7068, 0.8608, 0.9220, 10.17),
    ("knapsack beam (10)", 0.7283, 0.4223, 0.7072, 0.8550, 0.9234, 25.40),
    ("InstaNovo+ diffusion only", 0.7142, 0.4205, 0.6946, 0.8658, 0.9109, 2.80),
    ("greedy + refinement", 0.6964, 0.4123, 0.6776, 0.8390, 0.8812, 2.88),
    ("beam (10) + refinement", 0.7317, 0.4438, 0.7140, 0.8639, 0.9257, 20.80),
    ("knapsack beam (10) + refinement", 0.7321, 0.4437, 0.7142, 0.8621, 0.9260, 35.83),
]

# ProteoBench, InstaNovo v1.3.0 — only greedy has landed (experiment 9685299a,
# metrics_summary.csv). The other six are running.
PB_V130_GREEDY = {"pep_mass": 0.695058, "pep_exact": 0.447481, "aa_mass": 0.834528, "hours": 1.87}

# ── internal held-out sets, pooled over all 17 (scored with ProteoBench's own scorer) ───
# mode, pep/mass, aa/mass, pep AUC, wall clock
INTERNAL_V130 = [
    ("greedy", 0.5852, 0.7289, 0.8668, "5 h 40 m"),
    ("greedy + refinement", 0.5823, 0.7249, 0.8056, "8 h 42 m"),
    ("knapsack beam-5", 0.6458, 0.7813, 0.8851, "121 h"),
    ("knapsack beam-5 + refinement", 0.6408, 0.7771, 0.8357, "8 h 57 m"),
]
INTERNAL_V122 = [
    ("greedy", 0.6031, 0.7483, 0.8785, "5 h 51 m"),
    ("diffusion only", 0.5885, 0.7600, 0.9364, "8 h 24 m"),
]

# ── per-dataset, per-checkpoint peptide/mass recall on the internal sets ────────────────
# Straight out of _scored/metrics.csv (level=peptide, evaluation=mass, ambiguity=baseline),
# i.e. ProteoBench's own scorer. dataset, v1.2.2, v1.3.0.
#
# NOTE: an existing chart of this comparison reports greedy means of 0.5745 -> 0.5772
# (+0.27 pp, v1.3.0 ahead). These numbers give 0.5883 -> 0.5781 (-1.02 pp, v1.3.0 behind),
# with six datasets flipping sign (yeast, mmazei, tomato, bacillus, ricebean, clambacteria).
# The two are not the same quantity and the discrepancy is unresolved -- see README.md.
PER_DATASET_GREEDY = [
    ("herceptin", 0.7338, 0.8060),
    ("immuno", 0.7178, 0.7500),
    ("snakevenoms", 0.2032, 0.2181),
    ("tplantibodies", 0.4861, 0.4996),
    ("clambacteria", 0.4721, 0.4740),
    ("mmazei", 0.5888, 0.5860),
    ("tomato", 0.6427, 0.6337),
    ("bacillus", 0.6437, 0.6333),
    ("sbrodae", 0.7487, 0.7341),
    ("yeast", 0.6387, 0.6217),
    ("mouse", 0.5511, 0.5287),
    ("ricebean", 0.6421, 0.6184),
    ("honeybee", 0.5350, 0.5109),
    ("helaqc", 0.6410, 0.6023),
    ("woundfluids", 0.3571, 0.3158),
    ("gluc", 0.8394, 0.7968),
    ("human", 0.5593, 0.4976),
]

# ── Winnow calibration study, beam10 on ProteoBench (Notion sections 5, 15, 26) ─────────
WINNOW_HEADLINE = [
    ("sTECE", "−0.04405"),
    ("TECE", "0.04405", ),
    ("tolerance", "0.005 (exceeded ~9×)"),
    ("confidence cutoff at 5% FDR", "0.781"),
    ("accepted PSMs", "504,692"),
    ("true error rate there", "9.40% (nominal 5%)"),
]
WINNOW_RANKING = [
    ("precision-coverage AUC", 0.8578, 0.8615, "−0.0037"),
    ("ROC AUC (rank quality)", 0.8772, 0.8885, "−0.0113"),
]
# species, n, empirical correctness, claimed confidence
WINNOW_SPECIES = [
    ("Candidatus endoloripes", 42676, 0.8542, 0.9465),
    ("Mus musculus", 14329, 0.8733, 0.9553),
    ("Apis mellifera", 60135, 0.8874, 0.9453),
    ("Bacillus subtilis", 74714, 0.9050, 0.9505),
    ("H. sapiens", 30311, 0.9197, 0.9621),
    ("Vigna mungo", 69605, 0.9088, 0.9460),
    ("Saccharomyces cerevisiae", 77223, 0.9197, 0.9517),
    ("Solanum lycopersicum", 72437, 0.9263, 0.9558),
    ("Methanosarcina mazei", 63262, 0.9172, 0.9450),
]
# decile, claimed, empirical
WINNOW_DECILES = [
    ("lowest", 0.0499, 0.0880),
    ("2nd", 0.3155, 0.4406),
    ("4th", 0.8527, 0.7652),
    ("5th", 0.9284, 0.8215),
    ("highest", 0.9851, 0.9825),
]
# feature, AUC on FDR-accepted subset, AUC on full coverage
WINNOW_FEATURES = [
    ("median_margin", 0.7756, 0.8893, "beam"),
    ("calibrated_confidence", 0.7502, 0.8772, "combined"),
    ("margin", 0.7568, 0.8736, "beam"),
    ("min_token_probability", 0.7503, 0.8679, "token"),
    ("complementary_ion_count", 0.5635, 0.6943, "Koina"),
    ("spectral_angle", 0.6023, 0.6730, "Koina"),
    ("longest_y_series", 0.5595, 0.6660, "Koina"),
    ("longest_b_series", 0.5041, 0.6128, "Koina"),
    ("xcorr", 0.4767, 0.5958, "Koina"),
]

# ── run inventory ───────────────────────────────────────────────────────────────────────
# One table per benchmark, because the two have genuinely different mode sets: ProteoBench
# was swept at beam width 10, the internal sets at width 5 (to match the knapsack run that
# already existed there). Sharing one column set silently dropped ProteoBench's
# knapsack_beam10 and printed spurious dashes for beam-5 columns it never had.
MODES_PB = ["greedy", "beam-10", "knapsack-10", "greedy+ref", "beam-10+ref", "knapsack-10+ref", "diffusion"]
MODES_INT = ["greedy", "beam-5", "beam-10", "knapsack-5", "greedy+ref", "beam-5+ref", "beam-10+ref", "knapsack-5+ref", "diffusion"]
STATUS = [
    ("ProteoBench nine-species balanced", MODES_PB, [
        ("v1.2.2", dict.fromkeys(MODES_PB, "done")),
        ("v1.3.0", {**dict.fromkeys(MODES_PB, "running"), "greedy": "done"}),
    ]),
    ("Internal held-out (17 sets)", MODES_INT, [
        ("v1.3", {
            "greedy": "done", "greedy+ref": "done", "knapsack-5": "done", "knapsack-5+ref": "done",
            "beam-5": "scoring", "diffusion": "scoring", "beam-5+ref": "running", "beam-10": "running",
            "beam-10+ref": "planned",
        }),
        ("v1.2.2", {
            "greedy": "done", "diffusion": "done", "beam-5": "scoring", "beam-10": "running",
            "beam-5+ref": "running", "greedy+ref": "planned", "beam-10+ref": "planned",
            "knapsack-5": "skipped", "knapsack-5+ref": "skipped",
        }),
    ]),
]
STATUS_STYLE = {
    "done": ("●", "st-done", "scored"),
    "scoring": ("◐", "st-scoring", "run done, scoring"),
    "running": ("◑", "st-running", "running"),
    "planned": ("○", "st-planned", "planned"),
    "skipped": ("✕", "st-skipped", "deliberately not run"),
}


def esc(s) -> str:
    return html.escape(str(s))


def src(*parts: str) -> str:
    """Provenance line placed ABOVE a table or chart.

    Every table and chart in the deck carries one, so a reader landing on any slide can see
    which dataset and which checkpoint it belongs to without inferring it from the heading.
    """
    return '<p class="table-src">' + " &middot; ".join(esc(x) for x in parts) + "</p>"


# ══ chart helpers ══════════════════════════════════════════════════════════════════════

def svg(width: int, height: int, body: str, label: str) -> str:
    return (
        f'<svg viewBox="0 0 {width} {height}" width="100%" role="img" aria-label="{esc(label)}" '
        f'class="chart">{body}</svg>'
    )


def cost_scatter() -> str:
    """pep/mass against GPU hours for the seven v1.2.2 modes.

    A scatter, not bars: the question is the trade between two continuous quantities, and the
    shape of the answer -- a knee, then a flat run -- is the finding. One series, so no legend;
    every point is directly labelled instead.
    """
    W, H = 900, 430
    L, R, T, B = 70, 300, 24, 52
    xs = [m[6] for m in PB_V122]
    ys = [m[1] for m in PB_V122]
    x0, x1 = 0, 38
    y0, y1 = 0.685, 0.740

    def px(v):
        return L + (v - x0) / (x1 - x0) * (W - L - R)

    def py(v):
        return H - B - (v - y0) / (y1 - y0) * (H - B - T)

    parts = []
    for gv in [0.69, 0.70, 0.71, 0.72, 0.73, 0.74]:
        parts.append(f'<line x1="{L}" y1="{py(gv):.1f}" x2="{W-R}" y2="{py(gv):.1f}" stroke="{C_GRID}" stroke-width="1"/>')
        parts.append(f'<text x="{L-10}" y="{py(gv)+4:.1f}" text-anchor="end" class="tick">{gv:.2f}</text>')
    for gh in [0, 10, 20, 30]:
        parts.append(f'<text x="{px(gh):.1f}" y="{H-B+22}" text-anchor="middle" class="tick">{gh}</text>')
    parts.append(f'<line x1="{L}" y1="{H-B}" x2="{W-R}" y2="{H-B}" stroke="{C_GRID}" stroke-width="1"/>')

    # Pareto guide: cheapest mode reaching each accuracy level.
    frontier = sorted([(m[6], m[1], m[0]) for m in PB_V122])
    best = -1
    pts = []
    for hx, hy, _ in frontier:
        if hy > best:
            best = hy
            pts.append((hx, hy))
    path = " ".join(f"{px(a):.1f},{py(b):.1f}" for a, b in pts)
    parts.append(f'<polyline points="{path}" fill="none" stroke="{C_V122}" stroke-width="2" stroke-dasharray="5 4" opacity="0.5"/>')

    for name, pm, _pe, _il, _aa, _auc, hours in PB_V122:
        cx, cy = px(hours), py(pm)
        emph = "knapsack" in name
        parts.append(
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="7" fill="{C_V122}" stroke="var(--surface-1)" stroke-width="2">'
            f"<title>{esc(name)}: {pm:.4f} pep/mass, {hours:g} GPU h</title></circle>"
        )
        anchor = "start"
        dx = 14
        cls = "pt-label emph" if emph else "pt-label"
        parts.append(f'<text x="{cx+dx:.1f}" y="{cy+4:.1f}" text-anchor="{anchor}" class="{cls}">{esc(name)}</text>')
    parts.append(f'<text x="{(L+W-R)/2:.0f}" y="{H-6}" text-anchor="middle" class="axis-title">GPU hours</text>')
    parts.append(f'<text x="16" y="{T+8}" class="axis-title">pep/mass precision</text>')
    return svg(W, H, "".join(parts), "Peptide mass-match precision against GPU hours for seven decoding modes")


def grouped_bars(rows, series_labels, colors, title_label, fmt="{:.4f}", vmin=None, vmax=None, height=360):
    """Grouped bars: rows = [(group label, [v1, v2, ...])]. Legend + direct value labels."""
    W, H = 900, height
    L, R, T, B = 96, 30, 40, 64
    flat = [v for _, vs in rows for v in vs if v is not None]
    lo = vmin if vmin is not None else min(flat) * 0.97
    hi = vmax if vmax is not None else max(flat) * 1.02
    n_groups = len(rows)
    band = (W - L - R) / n_groups
    bw = min(64, band / (len(series_labels) + 0.8))

    def py(v):
        return H - B - (v - lo) / (hi - lo) * (H - B - T)

    parts = []
    for i in range(5):
        gv = lo + (hi - lo) * i / 4
        parts.append(f'<line x1="{L}" y1="{py(gv):.1f}" x2="{W-R}" y2="{py(gv):.1f}" stroke="{C_GRID}" stroke-width="1"/>')
        parts.append(f'<text x="{L-10}" y="{py(gv)+4:.1f}" text-anchor="end" class="tick">{gv:.3f}</text>')
    for gi, (label, vals) in enumerate(rows):
        gx = L + band * gi + band / 2
        total = len([v for v in vals if v is not None])
        for si, v in enumerate(vals):
            if v is None:
                continue
            # 2px surface gap between adjacent bars in a group
            x = gx - (total * bw + (total - 1) * 2) / 2 + si * (bw + 2)
            y = py(v)
            parts.append(
                f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{H-B-y:.1f}" rx="4" fill="{colors[si]}">'
                f"<title>{esc(series_labels[si])} — {esc(label)}: {fmt.format(v)}</title></rect>"
            )
            parts.append(f'<text x="{x+bw/2:.1f}" y="{y-8:.1f}" text-anchor="middle" class="bar-label">{fmt.format(v)}</text>')
        parts.append(f'<text x="{gx:.1f}" y="{H-B+22}" text-anchor="middle" class="tick strong">{esc(label)}</text>')
    parts.append(f'<line x1="{L}" y1="{H-B}" x2="{W-R}" y2="{H-B}" stroke="{C_GRID}" stroke-width="1"/>')
    legend = "".join(
        f'<span class="key"><i style="background:{colors[i]}"></i>{esc(lab)}</span>' for i, lab in enumerate(series_labels)
    )
    return f'<div class="legend">{legend}</div>' + svg(W, H, "".join(parts), title_label)


def species_bars() -> str:
    """Over-confidence per species: magnitude, one series, sorted -- horizontal bars."""
    W, H = 900, 400
    L, R, T, B = 250, 90, 16, 34
    rows = sorted(WINNOW_SPECIES, key=lambda r: (r[3] - r[2]), reverse=True)
    hi = 0.10
    row_h = (H - T - B) / len(rows)
    parts = []
    for gv in [0, 0.025, 0.05, 0.075, 0.10]:
        x = L + gv / hi * (W - L - R)
        parts.append(f'<line x1="{x:.1f}" y1="{T}" x2="{x:.1f}" y2="{H-B}" stroke="{C_GRID}" stroke-width="1"/>')
        parts.append(f'<text x="{x:.1f}" y="{H-B+22}" text-anchor="middle" class="tick">{gv:+.3f}</text>')
    for i, (name, n, emp, claim) in enumerate(rows):
        gap = claim - emp
        y = T + i * row_h + 4
        w = gap / hi * (W - L - R)
        parts.append(
            f'<rect x="{L}" y="{y:.1f}" width="{w:.1f}" height="{row_h-8:.1f}" rx="4" fill="{C_OVER}">'
            f"<title>{esc(name)}: claims {claim:.4f}, achieves {emp:.4f} (n={n:,})</title></rect>"
        )
        parts.append(f'<text x="{L-12}" y="{y+row_h/2:.1f}" text-anchor="end" class="tick strong">{esc(name)}</text>')
        parts.append(f'<text x="{L+w+10:.1f}" y="{y+row_h/2:.1f}" class="bar-label">+{gap:.4f}</text>')
    parts.append(f'<line x1="{L}" y1="{T}" x2="{L}" y2="{H-B}" stroke="{C_GRID}" stroke-width="1"/>')
    parts.append(f'<text x="{(L+W-R)/2:.0f}" y="{H-4}" text-anchor="middle" class="axis-title">claimed confidence − empirical correctness</text>')
    return svg(W, H, "".join(parts), "Over-confidence by species, three-fold range")


def decile_bars() -> str:
    """Calibration gap by score decile: polarity, so a diverging pair around zero."""
    W, H = 900, 330
    L, R, T, B = 90, 40, 30, 58
    rows = WINNOW_DECILES
    span = 0.14
    band = (W - L - R) / len(rows)
    mid = T + (H - T - B) / 2

    def py(v):
        return mid - v / span * (H - T - B) / 2

    parts = []
    for gv in [-0.12, -0.06, 0, 0.06, 0.12]:
        parts.append(f'<line x1="{L}" y1="{py(gv):.1f}" x2="{W-R}" y2="{py(gv):.1f}" stroke="{C_GRID}" stroke-width="1"/>')
        parts.append(f'<text x="{L-10}" y="{py(gv)+4:.1f}" text-anchor="end" class="tick">{gv:+.2f}</text>')
    for i, (label, claim, emp) in enumerate(rows):
        gap = claim - emp
        cx = L + band * i + band / 2
        bw = min(78, band * 0.5)
        y = min(py(gap), mid)
        h = abs(py(gap) - mid)
        colour = C_OVER if gap > 0 else C_UNDER
        parts.append(
            f'<rect x="{cx-bw/2:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{h:.1f}" rx="4" fill="{colour}">'
            f"<title>{esc(label)} decile: claims {claim:.4f}, achieves {emp:.4f}</title></rect>"
        )
        vy = y - 8 if gap > 0 else y + h + 18
        parts.append(f'<text x="{cx:.1f}" y="{vy:.1f}" text-anchor="middle" class="bar-label">{gap:+.3f}</text>')
        parts.append(f'<text x="{cx:.1f}" y="{H-B+34}" text-anchor="middle" class="tick strong">{esc(label)}</text>')
    parts.append(f'<line x1="{L}" y1="{mid:.1f}" x2="{W-R}" y2="{mid:.1f}" stroke="var(--text-secondary)" stroke-width="2"/>')
    parts.append(f'<text x="{W-R}" y="{mid-10:.1f}" text-anchor="end" class="tick">over-confident ↑</text>')
    parts.append(f'<text x="{W-R}" y="{mid+22:.1f}" text-anchor="end" class="tick">under-confident ↓</text>')
    return svg(W, H, "".join(parts), "Calibration gap by score decile, sign changes across the range")


def feature_dumbbell() -> str:
    """Per-feature AUC on the FDR-accepted subset versus full coverage."""
    W, H = 900, 430
    L, R, T, B = 250, 60, 30, 46
    rows = sorted(WINNOW_FEATURES, key=lambda r: r[2], reverse=True)
    lo, hi = 0.45, 0.92
    row_h = (H - T - B) / len(rows)

    def px(v):
        return L + (v - lo) / (hi - lo) * (W - L - R)

    parts = []
    for gv in [0.5, 0.6, 0.7, 0.8, 0.9]:
        parts.append(f'<line x1="{px(gv):.1f}" y1="{T}" x2="{px(gv):.1f}" y2="{H-B}" stroke="{C_GRID}" stroke-width="1"/>')
        parts.append(f'<text x="{px(gv):.1f}" y="{H-B+22}" text-anchor="middle" class="tick">{gv:.1f}</text>')
    for i, (name, acc, full, src) in enumerate(rows):
        y = T + i * row_h + row_h / 2
        parts.append(f'<line x1="{px(acc):.1f}" y1="{y:.1f}" x2="{px(full):.1f}" y2="{y:.1f}" stroke="{C_MUTED}" stroke-width="2"/>')
        parts.append(
            f'<circle cx="{px(acc):.1f}" cy="{y:.1f}" r="6" fill="{C_V122}" stroke="var(--surface-1)" stroke-width="2">'
            f"<title>{esc(name)} on the FDR-accepted subset: {acc:.4f}</title></circle>"
        )
        parts.append(
            f'<circle cx="{px(full):.1f}" cy="{y:.1f}" r="6" fill="{C_V130}" stroke="var(--surface-1)" stroke-width="2">'
            f"<title>{esc(name)} on full coverage: {full:.4f}</title></circle>"
        )
        cls = "tick strong" if src == "Koina" else "tick"
        parts.append(f'<text x="{L-12}" y="{y+4:.1f}" text-anchor="end" class="{cls}">{esc(name)}<tspan class="src"> {esc(src)}</tspan></text>')
        parts.append(f'<text x="{px(full)+12:.1f}" y="{y+4:.1f}" class="bar-label">{full:.3f}</text>')
    parts.append(f'<line x1="{L}" y1="{T}" x2="{L}" y2="{H-B}" stroke="{C_GRID}" stroke-width="1"/>')
    parts.append(f'<text x="{(L+W-R)/2:.0f}" y="{H-6}" text-anchor="middle" class="axis-title">AUC against correctness</text>')
    legend = (
        f'<span class="key"><i style="background:{C_V122}"></i>FDR-accepted subset only</span>'
        f'<span class="key"><i style="background:{C_V130}"></i>full coverage (721,739 PSMs)</span>'
    )
    return f'<div class="legend">{legend}</div>' + svg(W, H, "".join(parts), "Feature discrimination, accepted subset versus full coverage")


def per_dataset_dumbbell() -> str:
    """Per-dataset dumbbells, one row per held-out set, sorted by the change.

    A dumbbell rather than paired bars: the reader's question is the size and direction of the
    move per dataset, and a connecting segment encodes that directly. Two series, so a legend is
    present and each row carries its own delta label.
    """
    W, H = 900, 470
    L, R, T, B = 160, 96, 26, 44
    rows = sorted(PER_DATASET_GREEDY, key=lambda r: (r[2] - r[1]), reverse=True)
    lo, hi = 0.18, 0.88
    row_h = (H - T - B) / len(rows)

    def px(v):
        return L + (v - lo) / (hi - lo) * (W - L - R)

    parts = []
    for gv in [0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]:
        parts.append(f'<line x1="{px(gv):.1f}" y1="{T}" x2="{px(gv):.1f}" y2="{H-B}" stroke="{C_GRID}" stroke-width="1"/>')
        parts.append(f'<text x="{px(gv):.1f}" y="{H-B+20}" text-anchor="middle" class="tick">{gv:.1f}</text>')
    for i, (name, a, b) in enumerate(rows):
        y = T + i * row_h + row_h / 2
        dpp = (b - a) * 100
        parts.append(f'<line x1="{px(a):.1f}" y1="{y:.1f}" x2="{px(b):.1f}" y2="{y:.1f}" stroke="{C_MUTED}" stroke-width="2"/>')
        parts.append(
            f'<circle cx="{px(a):.1f}" cy="{y:.1f}" r="5.5" fill="{C_V122}" stroke="var(--surface-1)" stroke-width="2">'
            f"<title>{esc(name)} v1.2.2: {a:.4f}</title></circle>"
        )
        parts.append(
            f'<circle cx="{px(b):.1f}" cy="{y:.1f}" r="5.5" fill="{C_V130}" stroke="var(--surface-1)" stroke-width="2">'
            f"<title>{esc(name)} v1.3.0: {b:.4f}</title></circle>"
        )
        parts.append(f'<text x="{L-12}" y="{y+4:.1f}" text-anchor="end" class="tick strong">{esc(name)}</text>')
        far = max(px(a), px(b)) + 12
        cls = "bar-label" if abs(dpp) < 3 else "bar-label emph"
        parts.append(f'<text x="{far:.1f}" y="{y+4:.1f}" class="{cls}">{dpp:+.1f}</text>')
    parts.append(f'<line x1="{L}" y1="{T}" x2="{L}" y2="{H-B}" stroke="{C_GRID}" stroke-width="1"/>')
    parts.append(f'<text x="{(L+W-R)/2:.0f}" y="{H-6}" text-anchor="middle" class="axis-title">peptide/mass recall — greedy decoding</text>')
    legend = (
        f'<span class="key"><i style="background:{C_V122}"></i>v1.2.2</span>'
        f'<span class="key"><i style="background:{C_V130}"></i>v1.3.0 (133 residues)</span>'
        f'<span class="key muted">labels are the change in percentage points</span>'
    )
    return f'<div class="legend">{legend}</div>' + svg(W, H, "".join(parts), "Per-dataset peptide recall, v1.2.2 against v1.3.0, greedy decoding")


def status_matrix() -> str:
    """One table per benchmark. Every cell is a mode that benchmark actually has, so there are
    no placeholder dashes to misread as missing work."""
    tables = []
    for bench, modes, arms in STATUS:
        header = "".join(f"<th>{esc(m)}</th>" for m in modes)
        rows = []
        for ver, states in arms:
            cells = []
            for m in modes:
                glyph, cls, tip = STATUS_STYLE[states[m]]
                cells.append(f'<td class="{cls}" title="{esc(tip)}">{glyph}</td>')
            rows.append(f"<tr><th class='rowhead'>{esc(ver)}</th>{''.join(cells)}</tr>")
        tables.append(
            src(bench, "checkpoint per row")
            + f"<table class='matrix'><tr><th></th>{header}</tr>{''.join(rows)}</table>"
        )
    key = " ".join(
        f'<span class="key"><b class="{cls}">{g}</b>{esc(t)}</span>' for g, cls, t in STATUS_STYLE.values()
    )
    note = (
        "<p class='note'>The two benchmarks were swept at different beam widths &mdash; 10 on ProteoBench, "
        "5 internally, to match the knapsack run that already existed there &mdash; so their mode sets differ "
        "and are listed separately. The two internal knapsack cells are crossed rather than pending: the v1.3 "
        "knapsack beam-5 run cost <b>121 h</b> to test the one comparison that came back non-significant, so "
        "the v1.2.2 counterpart was deliberately not launched.</p>"
    )
    return "".join(tables) + f"<div class='legend'>{key}</div>{note}"


def pb_table() -> str:
    """The v1.2.2 sweep, with the best value in each metric column bolded.

    Per column, not per row: no single mode wins everything. Knapsack beam-10 + refinement takes
    pep/mass, exact+IL and AUC; plain beam-10 + refinement takes pep/exact by 0.0001; and
    diffusion-only takes aa/mass outright. Bolding a whole row would assert a clean sweep that
    the numbers do not support.

    GPU time is deliberately left unbolded -- it is a cost, so "highest" would mark the worst
    mode, and marking the lowest would put a winner's emphasis on the least accurate one.
    """
    cols = ["pep/mass", "pep/exact", "exact+IL", "aa/mass", "pep AUC"]
    values = [[m[i + 1] for m in PB_V122] for i in range(5)]
    best_at = [max(range(len(PB_V122)), key=lambda r: values[c][r]) for c in range(5)]

    head = "<tr><th>Mode</th>" + "".join(f"<th>{esc(c)}</th>" for c in cols) + "<th>GPU</th></tr>"
    rows = []
    for ri, (name, *metrics, hours) in enumerate(PB_V122):
        cells = []
        for ci in range(5):
            v = metrics[ci]
            cls = " class='best-cell'" if best_at[ci] == ri else ""
            cells.append(f"<td{cls}>{v:.4f}</td>")
        rows.append(
            f"<tr><td class='mode'>{esc(name)}</td>{''.join(cells)}<td class='num cost'>{hours:g} h</td></tr>"
        )
    return f"<table class='data'>{head}{''.join(rows)}</table>"


def internal_table() -> str:
    head = "<tr><th>Mode</th><th>checkpoint</th><th>pep/mass</th><th>aa/mass</th><th>pep AUC</th><th>wall clock</th></tr>"
    rows = []
    for label, data, ckpt, colour in (("v1.3", INTERNAL_V130, "v1.3", C_V130), ("v1.2.2", INTERNAL_V122, "v1.2.2", C_V122)):
        for name, pm, aa, auc, wall in data:
            rows.append(
                f"<tr><td class='mode'>{esc(name)}</td>"
                f"<td><span class='dot' style='background:{colour}'></span>{esc(ckpt)}</td>"
                f"<td>{pm:.4f}</td><td>{aa:.4f}</td><td>{auc:.4f}</td><td class='num'>{esc(wall)}</td></tr>"
            )
    return f"<table class='data'>{head}{''.join(rows)}</table>"


# ══ slides ═════════════════════════════════════════════════════════════════════════════

SLIDES = []


def slide(markup: str) -> None:
    SLIDES.append(f"<section>{markup}</section>")


slide("""
<h1>InstaNovo on two benchmarks</h1>
<p class="lede">v1.2.2 and v1.3.0, seven decoding modes, and what the confidence scores are worth</p>
<p class="sub">ProteoBench nine-species balanced &middot; 17 internal held-out sets &middot; Winnow calibration<br>
<span class="muted">Status as of 2026-08-17. Several runs are still in flight; every such number is marked.</span></p>
""")

slide(f"""
<h2>What is being compared</h2>
<p class="lede">Two checkpoints &times; two benchmarks &times; the decoding modes that matter.</p>
{status_matrix()}
<p class="note">The v1.2.2 arm on ProteoBench is complete and is the reference everything else is read
against; the v1.3.0 arm on the same data is one mode in, with six running. Internally both checkpoints
share one harness and one dataset list, so only the weights vary.</p>
""")

slide(f"""
<h2>Decoding choice moves accuracy more than anything else</h2>
{src("ProteoBench nine-species balanced", "779,879 spectra", "InstaNovo v1.2.2")}
{pb_table()}
<p class="note">Refined modes are <b>confidence-gated at 0.9</b> as shipped &mdash; not refined unconditionally. Bold marks the best value in
each column: no mode sweeps them. Knapsack beam-10 + refinement takes pep/mass, exact+IL and AUC; plain
beam-10 + refinement takes pep/exact by <b>0.0001</b>; diffusion-only takes aa/mass outright. GPU time is a
cost, so it carries no winner.</p>
<p class="note warn">Treat the two leads over plain beam-10 + refinement as ties, not results. The paired
test on the pep/exact pair is the single <b>non-significant</b> comparison of 42 (next slide): +0.000099,
95% CI &minus;0.000503 to +0.000671. The bold marks the larger number, not a real difference.</p>
""")

slide(f"""
<h2>...but the last increments cost the most</h2>
{src("ProteoBench nine-species balanced", "779,879 spectra", "InstaNovo v1.2.2")}
{cost_scatter()}
<p class="note">Beam search over greedy buys <b>+0.0332</b> for ~7&times; the GPU. The knapsack constraint then
buys <b>+0.0005</b> for another 2.5&times;. The dashed line is the cheapest mode reaching each accuracy level.</p>
""")

slide("""
<h2>Knapsack is the one comparison that fails to separate</h2>
<div class="two-col">
<div>
<p>All modes were scored on identical spectra, so differences were tested paired &mdash; McNemar plus a
paired bootstrap over 779,879 spectra.</p>
<p><b>42 comparisons, 41 significant at &alpha;=0.05.</b> The exception is knapsack beam-10 + refinement
against plain beam-10 + refinement at peptide/exact level:</p>
<p class="table-src">ProteoBench nine-species balanced &middot; InstaNovo v1.2.2 &middot; paired over 779,879 spectra</p>
<table class="data compact">
<tr><th>difference</th><td>+0.000099</td></tr>
<tr><th>95% CI</th><td>&minus;0.000503 to +0.000671</td></tr>
<tr><th>&chi;&sup2;</th><td>0.1</td></tr>
<tr><th>discordant</th><td>26,294 / 26,217</td></tr>
</table>
</div>
<div>
<p class="callout">At n = 779,879 significance is nearly free. <code>knap10 &gt; beam10</code> is
"significant" on a difference of <b>+0.0005</b>.</p>
<p>The informative columns are the effect size and the win ratio:</p>
<ul>
<li><b>beam over greedy</b> &mdash; 10.6:1 discordance. Close to a pure improvement.</li>
<li><b>refinement</b> &mdash; 1.19:1 to 1.45:1. Nearly a coin flip.</li>
<li><b>knapsack over beam</b> &mdash; 1.05:1. Indistinguishable where it matters.</li>
</ul>
</div>
</div>
""")

slide(f"""
<h2>Refinement: a small win here, a uniform loss there</h2>
{src("ProteoBench nine-species balanced", "779,879 spectra", "InstaNovo v1.2.2")}
{grouped_bars(
    [("greedy", [0.6946, 0.6964]), ("beam-10", [0.7278, 0.7317]), ("knapsack-10", [0.7283, 0.7321])],
    ["base", "+ InstaNovo+ refinement"], [C_V122, C_V130],
    "ProteoBench: refinement adds a small amount at every beam width", vmin=0.685, vmax=0.740, height=330)}
<p class="note">On ProteoBench, gated refinement adds <b>+0.0018 to +0.0039</b> pep/mass. On the internal
held-out sets the same operation on the v1.3 checkpoint is <b>negative in 17 of 17 datasets</b>, and
34 of 34 dataset-arm pairs across both checkpoints. That conclusion does not transfer &mdash; it reverses.</p>
""")

slide(f"""
<h2>v1.2.2 vs v1.3.0 on ProteoBench: the gain is all in <em>exact</em></h2>
{src("ProteoBench nine-species balanced", "779,879 spectra", "greedy decoding", "v1.2.2 vs v1.3.0")}
{grouped_bars(
    [("pep/mass", [0.6946, PB_V130_GREEDY["pep_mass"]]),
     ("pep/exact", [0.4045, PB_V130_GREEDY["pep_exact"]]),
     ("aa/mass", [0.8335, PB_V130_GREEDY["aa_mass"]])],
    ["v1.2.2", "v1.3.0"], [C_V122, C_V130],
    "Greedy decoding, same dataset: v1.2.2 against v1.3.0", vmin=0.38, vmax=0.88, height=340)}
<p class="note">Greedy only &mdash; the other six v1.3.0 modes are still running. Mass matching is a tie
(<b>+0.0005</b>); exact matching gains <b>+0.0430</b>. Mass forgives isobaric swaps and exact does not, so a
gain that appears only at exact level points at <b>modification and I/L calls</b>, which is what a
133-residue vocabulary would buy. Hypothesis, not conclusion: one mode, and <code>exact+IL</code> would test it.</p>
""")

slide(f"""
<h2>On our own data, the older checkpoint is ahead at greedy</h2>
{src("Internal held-out, 17 sets", "pooled over all spectra", "ProteoBench scorer")}
{internal_table()}
<p class="note">Pooled over 17 held-out sets, scored through ProteoBench's own scorer so the columns mean the
same thing as the previous slides. v1.2.2 greedy beats v1.3 greedy by <b>+0.0179</b> pep/mass and leads in
12 of 17 datasets &mdash; and the v1.3 wins cluster on antibody, immunopeptide and venom samples while v1.2.2
takes 8 of the 9 <code>ninespecies</code> sets. Beam search is worth <b>+0.0606</b> on v1.3, winning 17 of 17.</p>
<p class="note warn">The <code>aa AUC</code> for any refined or diffusion-only row is inflated and must not be
compared across rows: InstaNovo+ emits no per-token scores, so the peptide score is broadcast across residues.</p>
""")

slide(f"""
<h2>Per dataset, the greedy comparison is not close to uniform</h2>
{src("Internal held-out, 17 sets", "per dataset", "greedy decoding", "ProteoBench scorer, peptide/mass")}
{per_dataset_dumbbell()}
<p class="note">Unweighted mean across the 17 sets: <b>0.5883 &rarr; 0.5781</b>, i.e. v1.3.0 behind by
<b>1.02 pp</b>, ahead in only <b>5 of 17</b>. The wins are large and concentrated &mdash; herceptin
<b>+7.2</b>, immuno <b>+3.2</b> &mdash; and both are antibody or immunopeptide samples. The losses are broad,
with human <b>&minus;6.2</b> and gluc <b>&minus;4.3</b>. Spectrum-weighted pooling gives a wider gap still
(0.6031 &rarr; 0.5852), because the large <code>ninespecies</code> sets are where v1.2.2 leads.</p>
<p class="note warn"><b>Unresolved:</b> an existing version of this chart reports the greedy means as
0.5745 &rarr; 0.5772 (+0.27 pp, v1.3.0 <em>ahead</em>) with six datasets carrying the opposite sign
(yeast, mmazei, tomato, bacillus, ricebean, clambacteria). These figures come from
<code>_scored/metrics.csv</code>, i.e. ProteoBench's scorer at peptide/mass. The other chart's metric source
needs identifying before either is presented &mdash; they disagree on the direction of the headline.</p>
""")

slide(f"""
<h2>Cost is checkpoint-independent; knapsack is not</h2>
<div class="two-col">
<div>
<p class="table-src">Internal held-out, 17 sets &middot; wall clock &middot; identical hardware throughout</p>
<table class="data compact">
<tr><th>mode</th><th>v1.3</th><th>v1.2.2</th></tr>
<tr><td>greedy</td><td>5 h 40 m</td><td>5 h 51 m</td></tr>
<tr><td>beam-5</td><td>16 h 50 m</td><td>16 h 32 m</td></tr>
<tr><td>refinement pass</td><td>8 h 42 m</td><td class="na">&mdash;</td></tr>
<tr><td>diffusion only</td><td>19 h 33 m</td><td>8 h 24 m</td></tr>
<tr class="best"><td>knapsack beam-5</td><td>121 h</td><td class="na">not run</td></tr>
</table>
<p class="note">Internal held-out sets, identical hardware throughout.</p>
</div>
<div>
<ul>
<li><b>The two generations cost the same per spectrum</b> &mdash; agreeing within 2% at both greedy and
beam-5. Cost measured on one arm transfers to the other.</li>
<li><b>Refinement costs more than the decode it refines</b>, and its price barely depends on what it
refines (8 h 42 m on greedy, 8 h 57 m on knapsack beam-5). Refined modes are not cheap add-ons.</li>
<li><b>Knapsack costs 7.2&times; plain beam</b> at the same width &mdash; 121 h against 16 h 50 m. On
ProteoBench the same ratio was 2.5&times;, so this penalty did <em>not</em> transfer.</li>
<li><b>Diffusion-only is 2.3&times; slower on v1.3</b> &mdash; the one mode where the generations diverge.</li>
</ul>
</div>
</div>
""")

slide(f"""
<h2>The confidence scores do not mean what they say</h2>
<div class="two-col">
<div>
{src("ProteoBench nine-species balanced", "InstaNovo v1.2.2", "beam-10", "Winnow calibrate-estimate")}
<table class="data compact">
{''.join(f'<tr><th>{esc(k)}</th><td>{esc(v)}</td></tr>' for k, v in WINNOW_HEADLINE)}
</table>
<p class="note">Winnow calibrate-estimate on beam-10, Koina running in-pod as a Triton sidecar.
Reproduced to 16 significant figures on a rerun.</p>
</div>
<div>
<p class="callout">At the 5% FDR operating point the true error rate is <b>9.4%</b> &mdash; roughly
<b>47,000</b> wrong peptides among 504,692 accepted, where the FDR promises about 25,000.</p>
<p>The reliability curve sits below the diagonal <em>everywhere</em>, so this is systematic rather than
localised, and the gap <b>widens as the score falls</b>: near 0.99 it nearly touches the diagonal, at the
0.781 threshold empirical correctness is only ~0.75.</p>
<p><b>The miscalibration is worst exactly where the FDR cut is made.</b></p>
</div>
</div>
""")

slide(f"""
<h2>Least trustworthy on the hardest organisms</h2>
{src("ProteoBench nine-species balanced", "InstaNovo v1.2.2", "beam-10 top-1", "FDR-accepted set")}
{species_bars()}
<p class="note">The aggregate &minus;0.044 averages over a <b>three-fold range</b>. The two worst-calibrated
species are also the two with the highest unsolved rates, so the confidence is least reliable exactly where
a user would most want to lean on it.</p>
""")

slide(f"""
<h2>One number hides a sign change</h2>
{src("ProteoBench nine-species balanced", "InstaNovo v1.2.2", "beam-10", "all 721,739 scored PSMs")}
{decile_bars()}
<p class="note">Across the whole score range over-confidence is only <b>+0.0121</b> &mdash; because the ends
cancel. The model is <b>under</b>-confident at the bottom and <b>over</b>-confident in the middle, with the top
decile nearly perfect. This is why the tail-focused sTECE at the operating threshold is the more useful
summary for FDR control: it looks only where the threshold actually falls.</p>
""")

slide(f"""
<h2>Recalibration fixes the number, not the ranking</h2>
{src("ProteoBench nine-species balanced", "InstaNovo v1.2.2", "beam-10", "all 721,739 scored PSMs")}
<table class="data">
<tr><th>measure</th><th>Winnow calibrated</th><th>InstaNovo log-prob</th><th>difference</th></tr>
{''.join(f'<tr><td class="mode">{esc(m)}</td><td>{a:.4f}</td><td class="best-cell">{b:.4f}</td><td class="num">{d}</td></tr>' for m, a, b, d in WINNOW_RANKING)}
</table>
<div class="two-col">
<div>
<p>Measured on <b>all 721,739 scored PSMs</b> using ProteoBench's own precision-coverage definition.
Spearman between the two scores is <b>0.9275</b>, so the calibrated score genuinely reorders PSMs &mdash;
the reordering is just mildly harmful.</p>
</div>
<div>
<p class="callout">A Winnow-rescored submission would <b>not</b> move ProteoBench's AUC. What calibration
buys is a confidence that means what it says, which FDR control requires and a raw log-probability cannot
offer. That is a real result, and not a leaderboard improvement.</p>
</div>
</div>
""")

slide(f"""
<h2>Measuring on the accepted subset had understated every feature</h2>
{src("ProteoBench nine-species balanced", "InstaNovo v1.2.2", "beam-10", "Winnow calibrate-estimate")}
{feature_dumbbell()}
<p class="note">The first pass measured on the 504,692 FDR-accepted rows &mdash; a subset selected by
thresholding the very score under test. On full coverage every feature improves and the Koina fragment-match
features improve most: <code>xcorr</code> moves from apparently <em>inverse</em> (0.477) to informative (0.596).
An earlier claim that the Koina features "barely discriminate" was an artefact of that range restriction and is
withdrawn. One earlier finding survives: the calibrator's combined output (0.877) still does not beat its single
best input, <code>median_margin</code> (0.889).</p>
""")

slide("""
<h2>Where this stands</h2>
<div class="two-col">
<div>
<h3>Settled</h3>
<ul>
<li>Beam search is the intervention that pays; knapsack is not, on either benchmark.</li>
<li>Gated refinement is marginal on ProteoBench and negative on our data.</li>
<li>The confidence is over-confident by ~4.4 points at the operating threshold, worst on the hardest
organisms, and recalibration does not improve ranking.</li>
<li>Cost transfers between checkpoints; accuracy conclusions do not.</li>
</ul>
</div>
<div>
<h3>Open</h3>
<ul>
<li><b>Six v1.3.0 modes on ProteoBench</b> still running &mdash; greedy's exact-only gain needs the beam
modes and <code>exact+IL</code> to confirm.</li>
<li><b>Beam-10 on both internal arms</b> running; four v1.2.2 internal modes not yet launched.</li>
<li>Why <b>diffusion-only is 2.3&times; slower</b> on the v1.3 checkpoint.</li>
<li>A calibrator trained on a species-held-out split, to separate domain shift from intrinsic
miscalibration &mdash; and to cover the five modes that keep no beams.</li>
</ul>
</div>
</div>
""")

# ══ page ═══════════════════════════════════════════════════════════════════════════════

CSS = """
:root{color-scheme:light;
 --surface-1:#fcfcfb; --text-primary:#0b0b0b; --text-secondary:#52514e; --text-muted:#8a8985;
 --grid:#e6e5e1; --series-1:#2a78d6; --series-2:#eb6834;
 --diverge-warm:#e34948; --diverge-cool:#2a78d6; --best:#f4f8fd;}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])){
 color-scheme:dark; --surface-1:#1a1a19; --text-primary:#ffffff; --text-secondary:#c3c2b7;
 --text-muted:#8a8985; --grid:#383835; --series-1:#3987e5; --series-2:#d95926;
 --diverge-warm:#e66767; --diverge-cool:#3987e5; --best:#22262b;}}
:root[data-theme="dark"]{color-scheme:dark; --surface-1:#1a1a19; --text-primary:#ffffff;
 --text-secondary:#c3c2b7; --text-muted:#8a8985; --grid:#383835; --series-1:#3987e5;
 --series-2:#d95926; --diverge-warm:#e66767; --diverge-cool:#3987e5; --best:#22262b;}

.reveal{--r-main-font:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
 font-family:var(--r-main-font); color:var(--text-primary);}
.reveal-viewport{background:var(--surface-1);}
.reveal .slides{text-align:left;}
.reveal h1{font-size:1.9em; letter-spacing:-.02em; margin-bottom:.4em;}
.reveal h2{font-size:1.18em; letter-spacing:-.015em; margin:0 0 .7em; color:var(--text-primary); text-transform:none;}
.reveal h3{font-size:.8em; text-transform:uppercase; letter-spacing:.06em; color:var(--text-secondary); margin:0 0 .5em;}
.reveal p,.reveal li{font-size:.62em; line-height:1.45; color:var(--text-primary);}
.reveal .lede{font-size:.78em; color:var(--text-primary); margin-bottom:.5em;}
.reveal .sub{font-size:.58em; color:var(--text-secondary);}
.reveal .muted{color:var(--text-muted);}
.reveal .note{font-size:.5em; color:var(--text-secondary); line-height:1.5; margin-top:.7em;}
.reveal .note.warn{border-left:3px solid var(--diverge-warm); padding-left:.7em;}
.reveal .callout{font-size:.62em; background:var(--best); border-left:3px solid var(--series-1);
 padding:.6em .8em; border-radius:4px;}
.reveal code{font-size:.92em; background:var(--best); padding:.05em .3em; border-radius:3px;}
.two-col{display:grid; grid-template-columns:1fr 1fr; gap:1.6em; align-items:start;}
.reveal ul{margin-left:1em;} .reveal li{margin-bottom:.4em;}

table.data,table.matrix{border-collapse:collapse; width:100%; font-size:.46em; margin:0;}
table.data th,table.data td{padding:.42em .5em; text-align:right; border-bottom:1px solid var(--grid);}
table.data th{color:var(--text-secondary); font-weight:600; text-align:right; white-space:nowrap;}
table.data td.mode,table.data th:first-child{text-align:left;}
table.data tr.best{background:var(--best);}
table.data tr.best td{font-weight:700;}
table.data td.best-cell{font-weight:700;}
table.data td.na,table.matrix td.na{color:var(--text-muted);}
table.data.compact{width:auto;} table.data.compact th{text-align:left;}
table.matrix{font-size:.44em; text-align:center;}
table.matrix th{padding:.4em .3em; color:var(--text-secondary); font-weight:600; font-size:.92em;}
table.matrix th.rowhead{text-align:left; white-space:nowrap; color:var(--text-primary);}
table.matrix td{padding:.4em .3em; font-size:1.3em; border-bottom:1px solid var(--grid);}
.st-done{color:var(--series-1);} .st-scoring{color:var(--series-2);}
.st-running{color:var(--series-2); opacity:.75;} .st-planned{color:var(--text-muted);}
.st-skipped{color:var(--text-muted); opacity:.8;}
.table-src{font-size:.44em !important; color:var(--text-secondary); margin:.55em 0 .35em;
 letter-spacing:.02em; font-weight:600;}
.table-src:first-child{margin-top:0;}
table.matrix{margin-bottom:.2em;}
.dot{display:inline-block; width:.6em; height:.6em; border-radius:50%; margin-right:.4em;}

.legend{display:flex; gap:1.2em; flex-wrap:wrap; margin:.2em 0 .5em; font-size:.46em;
 color:var(--text-secondary);}
.legend .key{display:inline-flex; align-items:center; gap:.4em;}
.legend .key i{width:.85em; height:.85em; border-radius:3px; display:inline-block;}
.legend .key b{font-size:1.2em; line-height:1;}

svg.chart{display:block; max-width:100%; height:auto;}
svg.chart .tick{font-size:12px; fill:var(--text-secondary);}
svg.chart .tick.strong{fill:var(--text-primary); font-weight:600;}
svg.chart .tick .src{fill:var(--text-muted); font-weight:400;}
svg.chart .axis-title{font-size:12px; fill:var(--text-secondary); font-weight:600;}
svg.chart .bar-label{font-size:12px; fill:var(--text-primary); font-weight:600;}
svg.chart .pt-label{font-size:12.5px; fill:var(--text-primary);}
svg.chart .pt-label.emph{font-weight:700;}
"""

HTML = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>InstaNovo on two benchmarks</title>
<link rel="stylesheet" href="vendor/reveal.css">
<link rel="stylesheet" href="vendor/white.css" id="theme">
<style>{CSS}</style>
</head>
<body>
<div class="reveal"><div class="slides">
{chr(10).join(SLIDES)}
</div></div>
<script src="vendor/reveal.js"></script>
<script>
  Reveal.initialize({{hash:true, slideNumber:'c/t', width:1280, height:800, margin:0.06,
                     minScale:0.2, maxScale:1.6, transition:'fade'}});
</script>
</body>
</html>
"""

OUT.write_text(HTML)
print(f"wrote {OUT} ({len(HTML):,} bytes, {len(SLIDES)} slides)")
