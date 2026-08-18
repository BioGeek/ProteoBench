"""Turn a probe's JSON payload on stdin into a short verdict on stdout.

The three probes emit different shapes, so the pass name selects the reporter. Kept as a file
rather than an inline -c string: the reporters need both quote styles and f-strings, which do not
survive being nested inside a shell heredoc.
"""

import html
import json
import re
import sys


def payload():
    m = re.search(r'<pre id="PROBE_RESULT">(.*?)</pre>', sys.stdin.read(), re.S)
    if not m:
        print("  FAILED: the probe produced no result (did the page error?)")
        raise SystemExit(1)
    return json.loads(html.unescape(m.group(1)))


# Fraction of the deck's own baseline scale below which a slide is called too small. Calibrated by
# eyeballing renders, not chosen a priori: the failure this check exists to catch was a slide fitting
# at 0.46 with 531px spilling off-screen, and slides at 0.84 read comfortably at presentation size.
# Set at 0.82 so real regressions still trip it while ordinary dense slides do not, because a
# threshold that fires on a legible slide gets satisfied by deleting content -- which is worse than
# the small type it was trying to prevent.
FIT_FLOOR = 0.82


def fit(data):
    """Frame spill, and how far each slide's shrink-to-fit scale falls below the deck baseline."""
    base = max(r["scale"] for r in data)
    out = []
    for r in data:
        spill = max(-r["sectionTop"], r["sectionBottom"], -r["sectionLeft"], r["sectionRight"])
        rel = r["scale"] / base
        if spill > 1:
            out.append(f'  SPILL slide {r["i"]} by {spill}px: {r["title"]}')
        elif rel < FIT_FLOOR:
            out.append(f'  small slide {r["i"]} at {rel * 100:.0f}% of baseline: {r["title"]}')
    return out or ["  ok: every slide inside the frame at full type size"]


def overlap(data):
    """Label-on-label collisions and any text drawn outside its chart's viewBox."""
    out = []
    for r in data:
        for x in r.get("esc", []):
            out.append(f'  slide {r["slide"]}: "{x["t"]}" escapes the viewBox')
        for x in r.get("hits", []):
            out.append(f'  slide {r["slide"]}: "{x["a"]}" overlaps "{x["b"]}" by {x["ox"]}x{x["oy"]}')
    return out or ["  ok: no overlapping labels, nothing outside a viewBox"]


def geometry(data):
    """Labels sitting on a data marker or struck through by a connector."""
    out = [
        f'  slide {r["slide"]}: "{x["t"]}" sits on a {x["kind"]}'
        for r in data
        for x in r["hits"]
    ]
    return out or ["  ok: no label sits on a marker or a connector"]


if __name__ == "__main__":
    lines = {"fit": fit, "overlap": overlap, "geometry": geometry}[sys.argv[1]](payload())
    print("\n".join(lines))
    raise SystemExit(1 if not lines[0].startswith("  ok") else 0)
