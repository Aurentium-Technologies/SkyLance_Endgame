"""Original paired normalized-Elo GSPRT calculator, independent of engine code.

Numerical method: Michel Van den Bergh, Comments on Normalized Elo, section 4.1:
https://cantate.be/Fishtest/normalized_elo_practical.pdf
Only complete reversed-colour pairs are samples. Zero bins receive 0.001 counts
for the constrained fit; the likelihood uses actual observed counts. Numerical
failure raises rather than silently accepting an approximation or a patch.
"""
from __future__ import annotations

import math
from experiment import ExperimentError

SCORES = (0.0, 0.25, 0.5, 0.75, 1.0)
ELO_SCALE = 800.0 / math.log(10.0)
ZERO_COUNT = 0.001


def constrained_fit(counts, normalized_elo):
    """Fit probabilities with (mean-.5)/SD = sqrt(2)*nElo/scale."""
    adjusted = [max(ZERO_COUNT, count) for count in counts]
    total = sum(adjusted)
    frequency = [count / total for count in adjusted]
    target = math.sqrt(2.0) * normalized_elo / ELO_SCALE
    probability = [0.2] * 5
    for iteration in range(1, 201):
        mean = sum(p * x for p, x in zip(probability, SCORES))
        variance = sum(p * (x - mean) ** 2 for p, x in zip(probability, SCORES))
        sigma = math.sqrt(variance)
        if not sigma:
            raise ExperimentError("Degenerate constrained SPRT fit")
        gradient = [x - .5 - target * ((x - mean) ** 2 + variance) / (2 * sigma)
                    for x in SCORES]
        low_g, high_g = min(gradient), max(gradient)
        if not low_g < 0 < high_g:
            raise ExperimentError("SPRT likelihood fit has no valid multiplier bracket")
        low = math.nextafter(-1 / high_g, math.inf)
        high = math.nextafter(-1 / low_g, -math.inf)
        for _ in range(85):
            multiplier = (low + high) / 2
            if multiplier == low or multiplier == high:
                break
            residual = sum(f * g / (1 + multiplier * g) for f, g in zip(frequency, gradient))
            if residual > 0:
                low = multiplier
            else:
                high = multiplier
        multiplier = (low + high) / 2
        fitted = [f / (1 + multiplier * g) for f, g in zip(frequency, gradient)]
        normalizer = sum(fitted)
        fitted = [p / normalizer for p in fitted]
        # Damping retains the same fixed point and avoids oscillation for sparse
        # samples concentrated entirely on the losing end of the support.
        if target:
            fitted = [(old + new) / 2 for old, new in zip(probability, fitted)]
        change = max(abs(a - b) for a, b in zip(fitted, probability))
        probability = fitted
        if change < 1e-12:
            mean = sum(p * x for p, x in zip(probability, SCORES))
            variance = sum(p * (x - mean) ** 2 for p, x in zip(probability, SCORES))
            residual = mean - .5 - target * math.sqrt(variance)
            if abs(residual) > 1e-10 or not all(0 < p < 1 for p in probability):
                raise ExperimentError("SPRT constrained likelihood failed its residual check")
            return {"probabilities": probability, "iterations": iteration,
                    "constraint_residual": residual}
    raise ExperimentError("SPRT constrained likelihood did not converge")


def paired_sprt(pair_scores, elo0=0.0, elo1=5.0, alpha=.05, beta=.05):
    """Paired GSPRT state; input scores are totals 0,.5,1,1.5,2 per pair."""
    if not all(math.isfinite(v) for v in (elo0, elo1, alpha, beta)) or not elo0 < elo1:
        raise ExperimentError("Invalid SPRT hypothesis bounds")
    if not 0 < alpha < 1 or not 0 < beta < 1 or alpha + beta >= 1:
        raise ExperimentError("Invalid SPRT error probabilities")
    counts = [0] * 5
    for score in pair_scores:
        if type(score) not in (int, float) or score not in (0, .5, 1, 1.5, 2):
            raise ExperimentError("SPRT requires complete opening-pair scores")
        counts[int(score * 2)] += 1
    pairs = sum(counts)
    low, high = math.log(beta / (1 - alpha)), math.log((1 - beta) / alpha)
    record = {"method": "paired-normalized-elo-constrained-mle-v1", "pair_counts": counts,
              "completed_pairs": pairs, "completed_games": pairs * 2,
              "elo0": elo0, "elo1": elo1, "alpha": alpha, "beta": beta,
              "lower_bound": low, "upper_bound": high,
              "zero_bin_fit_count": ZERO_COUNT, "llr": 0.0, "verdict": "inconclusive"}
    if not pairs or counts[2] == pairs:
        record["note"] = "No non-neutral pair evidence; variance is zero"
        return record
    first, second = constrained_fit(counts, elo0), constrained_fit(counts, elo1)
    llr = sum(count * math.log(b / a) for count, a, b in
              zip(counts, first["probabilities"], second["probabilities"]))
    record.update(llr=llr, fit0=first, fit1=second,
                  verdict="accepted" if llr >= high else "rejected" if llr <= low else "inconclusive")
    return record
