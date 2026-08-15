"""Build per-beam candidate prediction files, and pick a winner across them.

Winnow scores the one prediction a row presents as top-1. To ask which of a beam
search's candidates it would have preferred, each beam has to be presented as the
top-1 in turn and scored, then the highest-scoring candidate kept per spectrum.

``split`` writes one candidate file per beam; ``combine`` reads the per-beam
prediction outputs back and picks the winner.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import pandas as pd

# A residue optionally carrying a modification, or a standalone (N-terminal) one.
# The residue alternatives come first so "C[UNIMOD:4]" is one token rather than two.
TOKEN_PATTERN = re.compile(r"[A-Z]\[UNIMOD:\d+\]|[A-Z]|\[UNIMOD:\d+\]")

TOP1_SEQUENCE = "predictions"
TOP1_TOKENS = "predictions_tokenised"
TOP1_LOGPROB = "log_probs"

BEAM_SEQUENCE = "predictions_beam_{k}"
BEAM_LOGPROB = "predictions_log_probability_beam_{k}"


def tokenise(sequence: object) -> str:
    """Render a peptide as the comma-separated token list the loader expects."""
    if not isinstance(sequence, str) or not sequence:
        return ""
    return ", ".join(TOKEN_PATTERN.findall(sequence))


def verify_tokeniser(df: pd.DataFrame, limit: int = 5000) -> None:
    """Check the tokeniser against InstaNovo's own output before relying on it.

    The top-1 columns already carry a tokenisation produced by InstaNovo, so
    re-deriving it from the sequence and comparing is a free correctness check.
    """
    sample = df.head(limit)
    rebuilt = sample[TOP1_SEQUENCE].map(tokenise)
    mismatches = sample.loc[rebuilt != sample[TOP1_TOKENS]]
    if len(mismatches):
        examples = mismatches[[TOP1_SEQUENCE, TOP1_TOKENS]].head(3).to_dict("records")
        raise SystemExit(
            f"tokeniser disagrees with InstaNovo on {len(mismatches)}/{len(sample)} rows: {examples}"
        )
    print(f"[beam_candidates] tokeniser matches InstaNovo on {len(sample):,} rows", flush=True)


def count_beams(df: pd.DataFrame) -> int:
    """How many beams the predictions file carries."""
    pattern = re.compile(r"^predictions_beam_(\d+)$")
    indices = [int(m.group(1)) for c in df.columns if (m := pattern.match(c))]
    return max(indices) + 1 if indices else 0


def split(predictions_path: Path, output_dir: Path, max_beams: int | None, only_beam: int | None = None) -> None:
    """Write one candidate predictions file per beam."""
    df = pd.read_csv(predictions_path, low_memory=False)
    verify_tokeniser(df)

    n_beams = count_beams(df)
    if n_beams == 0:
        raise SystemExit(f"{predictions_path} has no predictions_beam_<i> columns")
    if max_beams is not None:
        n_beams = min(n_beams, max_beams)
    print(f"[beam_candidates] {len(df):,} rows, using {n_beams} beam(s)", flush=True)

    output_dir.mkdir(parents=True, exist_ok=True)
    # One beam at a time keeps peak disk at a single candidate rather than all of them;
    # every candidate is nearly the size of the source file.
    wanted = range(n_beams) if only_beam is None else [only_beam]
    for k in wanted:
        sequence_col = BEAM_SEQUENCE.format(k=k)
        logprob_col = BEAM_LOGPROB.format(k=k)
        if sequence_col not in df.columns:
            raise SystemExit(f"missing {sequence_col}")

        candidate = df.copy()
        candidate[TOP1_SEQUENCE] = df[sequence_col]
        candidate[TOP1_TOKENS] = df[sequence_col].map(tokenise)
        candidate[TOP1_LOGPROB] = df[logprob_col]
        # A beam with no sequence is not a candidate; scoring it would only add noise.
        candidate = candidate[candidate[TOP1_SEQUENCE].notna() & (candidate[TOP1_TOKENS] != "")]

        destination = output_dir / f"beam_{k}.csv"
        candidate.to_csv(destination, index=False)
        print(f"[beam_candidates] wrote {destination} ({len(candidate):,} rows)", flush=True)


def combine(scored_dir: Path, output_path: Path, confidence_column: str) -> None:
    """Pick the highest-scoring candidate per spectrum across the scored beams."""
    frames = []
    for path in sorted(scored_dir.glob("beam_*/preds_and_fdr_metrics.csv")):
        beam = int(path.parent.name.split("_")[1])
        frame = pd.read_csv(path, low_memory=False)
        if confidence_column not in frame.columns:
            raise SystemExit(f"{path} lacks {confidence_column}; has {list(frame.columns)[:12]}")
        frame["beam"] = beam
        frames.append(frame)
    if not frames:
        raise SystemExit(f"no scored beams under {scored_dir}")

    everything = pd.concat(frames, ignore_index=True)
    winners = everything.loc[everything.groupby("spectrum_id")[confidence_column].idxmax()]
    winners = winners.sort_values("spectrum_id")

    changed = int((winners["beam"] != 0).sum())
    total = len(winners)
    print(
        f"[beam_candidates] {total:,} spectra; reranking moved {changed:,} "
        f"({changed / total:.2%}) off the model's own top-1",
        flush=True,
    )
    print(winners["beam"].value_counts().sort_index().to_string(), flush=True)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    winners.to_csv(output_path, index=False)
    print(f"[beam_candidates] wrote {output_path}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    p_split = sub.add_parser("split")
    p_split.add_argument("--predictions", type=Path, required=True)
    p_split.add_argument("--output-dir", type=Path, required=True)
    p_split.add_argument("--max-beams", type=int, default=None)
    p_split.add_argument("--only-beam", type=int, default=None)
    p_split.add_argument("--count-only", action="store_true")

    p_combine = sub.add_parser("combine")
    p_combine.add_argument("--scored-dir", type=Path, required=True)
    p_combine.add_argument("--output", type=Path, required=True)
    p_combine.add_argument("--confidence-column", default="calibrated_confidence")

    args = parser.parse_args()
    if args.command == "split":
        if args.count_only:
            df = pd.read_csv(args.predictions, nrows=1)
            n = count_beams(df)
            print(min(n, args.max_beams) if args.max_beams else n)
            return 0
        split(args.predictions, args.output_dir, args.max_beams, args.only_beam)
    else:
        combine(args.scored_dir, args.output, args.confidence_column)
    return 0


if __name__ == "__main__":
    sys.exit(main())
