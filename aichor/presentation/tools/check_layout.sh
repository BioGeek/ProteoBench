#!/usr/bin/env bash
# Headless layout check for index.html. Three passes, because they catch different defects and the
# first one alone gave a false all-clear:
#
#   fit       frame spill and fit scale. Reveal grows a section to fit its content and only ever
#             scales for the authored 1280x800, so an over-tall slide spills past the window edge.
#             The deck now shrinks to fit, which turns spill into a smaller render -- so this pass
#             also reports each slide's scale against the deck baseline. Below ~0.88 the slide
#             needs editing, not scaling.
#   overlap   text-vs-text collisions inside every chart, plus any label escaping its viewBox.
#   geometry  text over a data marker or a connector line. Grid lines are deliberately excluded:
#             a label crossing a faint gridline is normal, one crossing a data point is not.
#
# Usage: ./check_layout.sh [WIDTH,HEIGHT]   (default 1440,900)
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
deck="$here/../index.html"
vp="${1:-1440,900}"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
status=0

run() {   # $1 = probe filename, $2 = reporter name, $3 = heading
  python3 - "$deck" "$here/$1" "$tmp/p.html" <<'PY'
import pathlib, sys
deck, probe, out = (pathlib.Path(a) for a in sys.argv[1:4])
out.write_text("<!doctype html><html><head><meta charset='utf-8'></head><body>"
               + deck.read_text() + "<script>" + probe.read_text() + "</script></body></html>")
PY
  echo "── $3 ($vp)"
  google-chrome --headless=new --disable-gpu --no-sandbox --hide-scrollbars \
    --window-size="$vp" --virtual-time-budget=30000 --dump-dom "file://$tmp/p.html" 2>/dev/null \
    | python3 "$here/report.py" "$2" || status=1
}

run probe2.js fit      "frame fit"
run probe5.js overlap  "chart text overlap"
run probe6.js geometry "label over marker or line"
exit $status
