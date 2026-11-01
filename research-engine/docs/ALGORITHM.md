# Baseline algorithm v1

This baseline is a testable starting hypothesis. No weights, thresholds or clipping
anchors have been fitted, optimized or shown to be profitable. Scores are
dimensionless and are neither probabilities nor expected returns.

Let clip(x, a, b) = min(b, max(a, x)). A missing or stale factor has no normalized
value, contributes zero points and reduces weighted coverage.

| Factor | Weight | Normalized value in [-1, 1] |
| --- | ---: | --- |
| Momentum | 0.15 | clip(momentum_20d / 0.10, -1, 1) |
| Trend | 0.10 | clip(trend_50d / 0.10, -1, 1) |
| Volume confirmation | 0.10 | sign(momentum_20d) × clip((volume_ratio_20d - 1) / 2, 0, 1) |
| Profitability | 0.15 | clip((roce - 0.20) / 0.10, -1, 1) |
| Growth | 0.10 | clip((revenue_growth_yoy - 0.10) / 0.20, -1, 1) |
| Leverage | 0.10 | clip(1 - debt_to_equity, -1, 1) |
| Valuation | 0.10 | clip((1 - pe_to_sector_median) / 0.50, -1, 1) |
| News | 0.10 | news_sentiment |
| Announcements | 0.10 | announcement_impact |

The volume term requires both volume ratio and momentum. A volume surge during
falling prices contributes negatively; a flat price trend receives no volume bonus.
The default sum of weights is 1.0.

Let C be the sum of weights of available factors. Let z_j be each available
normalized factor, w_j its weight, and sigma the annualized 20-session volatility.

    factor_points = 50 × sum(w_j × z_j)
    missing_penalty = 15 × (1 - C)
    volatility_penalty = 10 × clip((sigma - 0.20) / 0.40, 0, 1)
    score = clip(50 + factor_points - missing_penalty - volatility_penalty, 0, 100)

Missing factors are not reweighted. Coverage is completeness, not confidence.
If volatility is missing, its score penalty is zero and a mandatory exclusion applies.
Changing the weights or penalties changes the research hypothesis and creates a new run.

## Hard exclusions

Regardless of score, exclude an asset if:

- close, average turnover, volatility or debt-to-equity is missing or stale;
- its price session is not the declared latest completed exchange session;
- weighted factor coverage is below 70%;
- average 20-session turnover is below INR 10,000,000;
- debt-to-equity exceeds 2.0;
- annualized volatility exceeds 0.80;
- it is in the financial sector, for which this generic quality model is unsuitable.

Freshness defaults: daily observations at most 7 calendar days old; fundamental
availability at most 200 days old and accounting observation at most 550 days old;
news at most 7 days old; announcements at most 14 days old. These are research
defaults, not exchange-specific filing rules. They are configurable.

An eligible asset scoring at least 65 is a candidate; another eligible asset is watch.
Rank within each status by unrounded score descending, then instrument ID ascending.
The shortlist contains up to top_n candidates, default 10, and can be empty.
An excluded asset can retain a high diagnostic score; it never enters the shortlist.

## Worked fixture

SIM-ASTER contributes 6 + 3 + 2 + 4.5 + 3 + 3 + 2 + 3 + 3.5 = 30 points.
It has full coverage, so its missing penalty is 0. Volatility 0.24 gives a 1-point
penalty. Final score = 50 + 30 - 0 - 1 = 79.

SIM-BANYAN has momentum 0.06 and missing news/announcements. Its factor points are
22, coverage 0.80, missing penalty 3 and risk penalty 1: 50 + 22 - 3 - 1 = 68.

The fixture report lists every contribution and source ID.

## Known limitations

The anchors are arbitrary research defaults. Momentum/trend and other correlated
inputs can double-count information. Sector differences remain even outside financials.
Negative equity makes debt-to-equity unusable and must produce a missing value, which
excludes the asset through the required-risk-input rule.

Missingness is not neutral information: omitting a sufficiently negative factor can
still raise a score despite the completeness penalty. This is why providers must
report coverage failures honestly and candidate eligibility has a coverage floor.
Do not tune missingness to improve the shortlist.

News and event values must arrive as sourced, bounded inputs. The core does not infer
them, invent them, treat them as verified facts or estimate their predictive accuracy.
An evidence link records provenance; it does not certify a causal effect.

There is no transaction-cost forecast in this dimensionless score. Cost-aware testing
belongs in the paper simulator and evaluation stage.

## Future forecasting equation

The previously discussed research target remains:

    utility_i,t = predicted_return_i,t - estimated_cost_i,t
                  - lambda × downside_i,t - kappa × uncertainty_i,t

All four terms must use the same horizon and return units; lambda and kappa are
dimensionless. The horizon initially proposed is 20 trading sessions.
This expression is not fitted or used by this release. We need actual point-in-time
data, suitable labels, calibrated uncertainty and cost-aware chronological tests
before replacing the baseline. Giving an equation a name does not establish an edge.
