"""Paired significance tests between de novo modes, from per-spectrum match indicators.

All modes are scored on the same 779,879 spectra, so differences between them should be
tested *paired* rather than with independent-proportion standard errors: the same spectrum
being easy or hard is common to both arms, and removing that shared variance is what makes
small differences testable.

Reads only the two needed columns from each mode's ``intermediate.csv`` (which are ~1.3GB
each) and reports, for every pair of modes:

* McNemar's exact-ish test on the discordant counts (b, c) -- the only spectra that carry
  information about which mode is better.
* A paired bootstrap CI over spectra, which unlike McNemar also covers the aggregate
  difference rather than just its sign.

Run this on AIchor: it needs no GPU, but streaming several 1.3GB CSVs wants headroom.
"""

from __future__ import annotations

import argparse
import json
import sys
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_sweep import fetch_predictions, finalize_outputs  # noqa: E402

# Published peptide-level precisions, used as a self-check that the indicator we derive
# from intermediate.csv is the same quantity ProteoBench reported.
PUBLISHED = {
    "greedy": {"mass": 0.694606, "exact": 0.404509},
    "greedy_refined": {"mass": 0.696408, "exact": 0.412266},
    "beam10": {"mass": 0.727818, "exact": 0.422150},
    "beam10_refined": {"mass": 0.731721, "exact": 0.443822},
    "knapsack_beam10": {"mass": 0.728269, "exact": 0.422278},
    "knapsack_beam10_refined": {"mass": 0.732120, "exact": 0.443725},
    "diffusion_only": {"mass": 0.714199, "exact": 0.420528},
}


def load_indicators(path: Path) -> pd.DataFrame:
    """Per-spectrum boolean match indicators, keyed by spectrum_id."""
    header = pd.read_csv(path, nrows=0).columns.tolist()
    wanted = [c for c in ("spectrum_id", "match_type", "pep_match") if c in header]
    if "spectrum_id" not in wanted or "match_type" not in wanted:
        raise ValueError(f"{path} lacks spectrum_id/match_type; has {header[:12]}")
    df = pd.read_csv(path, usecols=wanted, low_memory=False)
    out = pd.DataFrame({"spectrum_id": df["spectrum_id"]})
    # ProteoBench's peptide "mass" match is match_type in {exact, mass}; "exact" is the
    # stricter identity match. Verified against the published precisions below.
    out["mass"] = df["match_type"].isin(["exact", "mass"]).to_numpy()
    out["exact"] = (df["match_type"] == "exact").to_numpy()
    if "pep_match" in df.columns:
        out["pep_match"] = df["pep_match"].astype(bool).to_numpy()
    return out


def mcnemar(a: np.ndarray, b: np.ndarray) -> dict:
    """McNemar's test on paired binary outcomes.

    Only discordant spectra (one mode right, the other wrong) are informative. Uses the
    normal approximation with continuity correction; with tens of thousands of discordant
    pairs that is indistinguishable from the exact binomial.
    """
    b_count = int(np.sum(a & ~b))  # a right, b wrong
    c_count = int(np.sum(~a & b))  # b right, a wrong
    n_disc = b_count + c_count
    if n_disc == 0:
        return {"b": 0, "c": 0, "n_discordant": 0, "chi2": float("nan"), "z": float("nan")}
    chi2 = (abs(b_count - c_count) - 1) ** 2 / n_disc
    # Signed z, positive when the first mode wins more often.
    z = (b_count - c_count) / np.sqrt(n_disc)
    return {"b": b_count, "c": c_count, "n_discordant": n_disc, "chi2": float(chi2), "z": float(z)}


def paired_bootstrap(a: np.ndarray, b: np.ndarray, n_boot: int, seed: int) -> dict:
    """Bootstrap the paired difference in means by resampling spectra."""
    rng = np.random.default_rng(seed)
    diff = a.astype(np.int8) - b.astype(np.int8)
    n = diff.size
    means = np.empty(n_boot)
    for i in range(n_boot):
        means[i] = diff[rng.integers(0, n, n)].mean()
    lo, hi = np.percentile(means, [2.5, 97.5])
    return {"observed": float(diff.mean()), "ci95_low": float(lo), "ci95_high": float(hi), "boot_sd": float(means.std())}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--intermediate", action="append", default=[], metavar="MODE=PATH", required=True,
                    help="MODE=s3://.../intermediate.csv, repeatable")
    ap.add_argument("--work-dir", default="/workspace/proteobench_stats")
    ap.add_argument("--cache-dir", default=None,
                    help="Where to stage the downloaded intermediate CSVs. Keep it outside "
                         "--work-dir so the ~1.4GB inputs are not copied to the results "
                         "destination alongside the statistics. Defaults to --work-dir.")
    ap.add_argument("--output-prefix", default="instanovo_v1_2_2_paired_stats")
    ap.add_argument("--n-boot", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=20260813)
    args = ap.parse_args()

    work_dir = Path(args.work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = Path(args.cache_dir) if args.cache_dir else work_dir
    cache_dir.mkdir(parents=True, exist_ok=True)

    indicators = {}
    for entry in args.intermediate:
        mode, _, source = entry.partition("=")
        mode, source = mode.strip(), source.strip()
        local = fetch_predictions(source, cache_dir / mode / "intermediate.csv")
        ind = load_indicators(local)
        print(f"[{mode}] {len(ind):,} spectra", flush=True)
        for level in ("mass", "exact"):
            rate = float(ind[level].mean())
            expected = PUBLISHED.get(mode, {}).get(level)
            note = ""
            if expected is not None:
                note = f"  (published {expected:.6f}, diff {rate-expected:+.6f})"
            print(f"    peptide/{level} = {rate:.6f}{note}", flush=True)
        indicators[mode] = ind

    # Align every mode on spectrum_id so the pairing is exact rather than positional.
    modes = list(indicators)
    merged = None
    for mode in modes:
        cols = indicators[mode][["spectrum_id", "mass", "exact"]].rename(
            columns={"mass": f"{mode}__mass", "exact": f"{mode}__exact"})
        merged = cols if merged is None else merged.merge(cols, on="spectrum_id", how="inner")
    print(f"\naligned on spectrum_id: {len(merged):,} spectra common to all {len(modes)} modes", flush=True)

    results = []
    for level in ("mass", "exact"):
        print(f"\n=== peptide/{level}: paired comparisons ===", flush=True)
        for m1, m2 in combinations(modes, 2):
            a = merged[f"{m1}__{level}"].to_numpy()
            b = merged[f"{m2}__{level}"].to_numpy()
            mc = mcnemar(a, b)
            bs = paired_bootstrap(a, b, args.n_boot, args.seed)
            sig = "significant" if mc["chi2"] > 3.841 else "NOT significant"  # chi2 crit, df=1, alpha=.05
            row = {"level": level, "mode_a": m1, "mode_b": m2, **mc, **bs, "verdict_alpha05": sig}
            results.append(row)
            print(
                f"  {m1} vs {m2}: diff={bs['observed']:+.6f} "
                f"95%CI[{bs['ci95_low']:+.6f},{bs['ci95_high']:+.6f}] "
                f"discordant={mc['n_discordant']:,} (b={mc['b']:,} c={mc['c']:,}) "
                f"chi2={mc['chi2']:.1f} -> {sig}",
                flush=True,
            )

    table = pd.DataFrame(results)
    table.to_csv(work_dir / "paired_stats.csv", index=False)
    (work_dir / "paired_stats.json").write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print(f"\n{table.to_string(index=False)}", flush=True)
    finalize_outputs(work_dir, args.output_prefix)
    return 0


if __name__ == "__main__":
    sys.exit(main())
