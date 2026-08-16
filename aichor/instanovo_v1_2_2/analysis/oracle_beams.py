"""How often is the ground truth anywhere in the beam?

Bounds what reranking could ever achieve: no reranker can pick a correct answer that
the beam never contained. Reports the rate at each rank, so the shape of the decay is
visible rather than just the ceiling.

Matching is string equality after normalising notation, which reproduces ProteoBench's
"exact" and "exact+IL" levels but not its mass-based level (that allows isobaric
substitutions and needs the scoring code's tolerance logic). The beam-0 rates are
printed against ProteoBench's published values as a check on the normalisation.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

GT_PATH = Path(sys.argv[1])
PRED_PATH = Path(sys.argv[2])
N_BEAMS = 10

# ProteoBench writes an N-terminal group as "[UNIMOD:1]-PEPTIDE"; InstaNovo writes it
# without the separator. Neither the hyphen nor I/L identity should decide a match.
def normalise(seq: object) -> str:
    if not isinstance(seq, str):
        return ""
    return seq.replace("-", "").strip()


def il(seq: str) -> str:
    return seq.replace("I", "L")


print("[oracle] loading ground truth", flush=True)
gt = {}
for chunk in pd.read_csv(GT_PATH, usecols=["spectrum_id", "peptidoform_ground_truth"], chunksize=200_000):
    for sid, seq in zip(chunk["spectrum_id"], chunk["peptidoform_ground_truth"]):
        gt[sid] = normalise(seq)
print(f"[oracle] ground truth for {len(gt):,} spectra", flush=True)

beam_cols = [f"predictions_beam_{k}" for k in range(N_BEAMS)]
exact_hit_at = [0] * N_BEAMS      # beam k is an exact match
il_hit_at = [0] * N_BEAMS         # beam k matches once I/L are equated
exact_any = 0
il_any = 0
total = 0

print("[oracle] scanning beams", flush=True)
# The predictions key on "<experiment>:<scan>" while the scored table keys on the bare
# scan number, so the join goes through scan_number.
for chunk in pd.read_csv(PRED_PATH, usecols=["scan_number"] + beam_cols, chunksize=100_000, low_memory=False):
    for row in chunk.itertuples(index=False):
        truth = gt.get(row.scan_number)
        if truth is None:
            continue
        total += 1
        truth_il = il(truth)
        hit_e = hit_i = False
        for k in range(N_BEAMS):
            cand = normalise(getattr(row, f"predictions_beam_{k}"))
            if not cand:
                continue
            if cand == truth:
                exact_hit_at[k] += 1
                hit_e = True
            if il(cand) == truth_il:
                il_hit_at[k] += 1
                hit_i = True
        exact_any += hit_e
        il_any += hit_i
    print(f"  {total:,} spectra", flush=True)

print()
print(f"spectra compared: {total:,}")
print()
print(f"{'rank':>5}{'exact':>12}{'exact+IL':>12}   (rate at this rank)")
for k in range(N_BEAMS):
    print(f"{k:>5}{exact_hit_at[k]/total:>12.4f}{il_hit_at[k]/total:>12.4f}")
print()
print(f"{'oracle over 10 beams':<24}exact={exact_any/total:.4f}  exact+IL={il_any/total:.4f}")
print(f"{'top-1 (beam 0)':<24}exact={exact_hit_at[0]/total:.4f}  exact+IL={il_hit_at[0]/total:.4f}")
print(f"{'headroom':<24}exact={(exact_any-exact_hit_at[0])/total:+.4f}  exact+IL={(il_any-il_hit_at[0])/total:+.4f}")
print()
print("ProteoBench published for beam10: exact=0.4222  exact+IL=0.7068")
print("(beam-0 rows above should land on those if the normalisation is right)")
