# Oraculum research report

Mode: **synthetic** · As of: 2026-10-09T12:00:00Z

**Unvalidated baseline. Scores are neither return forecasts nor probabilities.**

Run ID: 7b3771f67835e89051787f86517c6e80d9ff530d9d39cb9acdfc515d3a130430

| Instrument | Status | Score | Coverage |
| --- | --- | ---: | ---: |
| NSE:SIM-ASTER | candidate | 79.00 | 100% |
| NSE:SIM-BANYAN | candidate | 68.00 | 80% |
| NSE:SIM-CEDAR | watch | 50.00 | 100% |
| NSE:SIM-DUNE | watch | 31.00 | 100% |
| NSE:SIM-EMBER | excluded | 79.00 | 100% |
| NSE:SIM-GROVE | excluded | 79.00 | 100% |
| NSE:SIM-HARBOR | excluded | 70.00 | 100% |
| NSE:SIM-FERN | excluded | 54.75 | 45% |

Shortlist: NSE:SIM-ASTER, NSE:SIM-BANYAN

## NSE:SIM-ASTER

- Supporting: momentum: +6.00 score points (momentum\_20d=0.08)
- Supporting: profitability: +4.50 score points (roce=0.26)
- Supporting: announcements: +3.50 score points (announcement\_impact=0.7)
- Counterargument / blocker: Volatility penalty: -1.00 points

| Factor | Weight | Normalized | Points | Sources |
| --- | ---: | ---: | ---: | --- |
| momentum | 0.15 | 0.8000 | +6.00 | demo-prices |
| trend | 0.10 | 0.6000 | +3.00 | demo-prices |
| volume_confirmation | 0.10 | 0.4000 | +2.00 | demo-prices |
| profitability | 0.15 | 0.6000 | +4.50 | demo-fundamentals |
| growth | 0.10 | 0.6000 | +3.00 | demo-fundamentals |
| leverage | 0.10 | 0.6000 | +3.00 | demo-fundamentals |
| valuation | 0.10 | 0.4000 | +2.00 | demo-fundamentals |
| news | 0.10 | 0.6000 | +3.00 | demo-news |
| announcements | 0.10 | 0.7000 | +3.50 | demo-announcements |

## NSE:SIM-BANYAN

- Supporting: momentum: +4.50 score points (momentum\_20d=0.06)
- Supporting: profitability: +4.50 score points (roce=0.26)
- Supporting: growth: +3.00 score points (revenue\_growth\_yoy=0.22)
- Counterargument / blocker: Missing or stale factors: -3.00 points
- Counterargument / blocker: Volatility penalty: -1.00 points
- Data issue: news: news\_sentiment: missing
- Data issue: announcements: announcement\_impact: missing

| Factor | Weight | Normalized | Points | Sources |
| --- | ---: | ---: | ---: | --- |
| momentum | 0.15 | 0.6000 | +4.50 | demo-prices |
| trend | 0.10 | 0.6000 | +3.00 | demo-prices |
| volume_confirmation | 0.10 | 0.4000 | +2.00 | demo-prices |
| profitability | 0.15 | 0.6000 | +4.50 | demo-fundamentals |
| growth | 0.10 | 0.6000 | +3.00 | demo-fundamentals |
| leverage | 0.10 | 0.6000 | +3.00 | demo-fundamentals |
| valuation | 0.10 | 0.4000 | +2.00 | demo-fundamentals |
| news | 0.10 | missing | +0.00 |  |
| announcements | 0.10 | missing | +0.00 |  |

## NSE:SIM-CEDAR

- Supporting: No positively contributing factors

| Factor | Weight | Normalized | Points | Sources |
| --- | ---: | ---: | ---: | --- |
| momentum | 0.15 | 0.0000 | +0.00 | demo-prices |
| trend | 0.10 | 0.0000 | +0.00 | demo-prices |
| volume_confirmation | 0.10 | 0.0000 | +0.00 | demo-prices |
| profitability | 0.15 | 0.0000 | +0.00 | demo-fundamentals |
| growth | 0.10 | 0.0000 | +0.00 | demo-fundamentals |
| leverage | 0.10 | 0.0000 | +0.00 | demo-fundamentals |
| valuation | 0.10 | 0.0000 | +0.00 | demo-fundamentals |
| news | 0.10 | 0.0000 | +0.00 | demo-news |
| announcements | 0.10 | 0.0000 | +0.00 | demo-announcements |

## NSE:SIM-DUNE

- Supporting: profitability: +4.50 score points (roce=0.26)
- Supporting: growth: +3.00 score points (revenue\_growth\_yoy=0.22)
- Supporting: leverage: +3.00 score points (debt\_to\_equity=0.4)
- Counterargument / blocker: momentum: -7.50 score points (momentum\_20d=-0.1)
- Counterargument / blocker: volume\_confirmation: -5.00 score points (volume\_ratio\_20d=3, momentum\_20d=-0.1)
- Counterargument / blocker: announcements: -4.00 score points (announcement\_impact=-0.8)
- Counterargument / blocker: Volatility penalty: -7.50 points

| Factor | Weight | Normalized | Points | Sources |
| --- | ---: | ---: | ---: | --- |
| momentum | 0.15 | -1.0000 | -7.50 | demo-prices |
| trend | 0.10 | -0.8000 | -4.00 | demo-prices |
| volume_confirmation | 0.10 | -1.0000 | -5.00 | demo-prices |
| profitability | 0.15 | 0.6000 | +4.50 | demo-fundamentals |
| growth | 0.10 | 0.6000 | +3.00 | demo-fundamentals |
| leverage | 0.10 | 0.6000 | +3.00 | demo-fundamentals |
| valuation | 0.10 | 0.4000 | +2.00 | demo-fundamentals |
| news | 0.10 | -0.7000 | -3.50 | demo-news |
| announcements | 0.10 | -0.8000 | -4.00 | demo-announcements |

## NSE:SIM-EMBER

- Supporting: momentum: +6.00 score points (momentum\_20d=0.08)
- Supporting: profitability: +4.50 score points (roce=0.26)
- Supporting: announcements: +3.50 score points (announcement\_impact=0.7)
- Counterargument / blocker: Volatility penalty: -1.00 points
- Counterargument / blocker: Average daily turnover below the configured liquidity floor

| Factor | Weight | Normalized | Points | Sources |
| --- | ---: | ---: | ---: | --- |
| momentum | 0.15 | 0.8000 | +6.00 | demo-prices |
| trend | 0.10 | 0.6000 | +3.00 | demo-prices |
| volume_confirmation | 0.10 | 0.4000 | +2.00 | demo-prices |
| profitability | 0.15 | 0.6000 | +4.50 | demo-fundamentals |
| growth | 0.10 | 0.6000 | +3.00 | demo-fundamentals |
| leverage | 0.10 | 0.6000 | +3.00 | demo-fundamentals |
| valuation | 0.10 | 0.4000 | +2.00 | demo-fundamentals |
| news | 0.10 | 0.6000 | +3.00 | demo-news |
| announcements | 0.10 | 0.7000 | +3.50 | demo-announcements |

## NSE:SIM-GROVE

- Supporting: momentum: +6.00 score points (momentum\_20d=0.08)
- Supporting: profitability: +4.50 score points (roce=0.26)
- Supporting: announcements: +3.50 score points (announcement\_impact=0.7)
- Counterargument / blocker: Volatility penalty: -1.00 points
- Counterargument / blocker: Financial-sector accounting requires a separate quality model

| Factor | Weight | Normalized | Points | Sources |
| --- | ---: | ---: | ---: | --- |
| momentum | 0.15 | 0.8000 | +6.00 | demo-prices |
| trend | 0.10 | 0.6000 | +3.00 | demo-prices |
| volume_confirmation | 0.10 | 0.4000 | +2.00 | demo-prices |
| profitability | 0.15 | 0.6000 | +4.50 | demo-fundamentals |
| growth | 0.10 | 0.6000 | +3.00 | demo-fundamentals |
| leverage | 0.10 | 0.6000 | +3.00 | demo-fundamentals |
| valuation | 0.10 | 0.4000 | +2.00 | demo-fundamentals |
| news | 0.10 | 0.6000 | +3.00 | demo-news |
| announcements | 0.10 | 0.7000 | +3.50 | demo-announcements |

## NSE:SIM-HARBOR

- Supporting: momentum: +6.00 score points (momentum\_20d=0.08)
- Supporting: profitability: +4.50 score points (roce=0.26)
- Supporting: announcements: +3.50 score points (announcement\_impact=0.7)
- Counterargument / blocker: Volatility penalty: -10.00 points
- Counterargument / blocker: Volatility exceeds the configured ceiling

| Factor | Weight | Normalized | Points | Sources |
| --- | ---: | ---: | ---: | --- |
| momentum | 0.15 | 0.8000 | +6.00 | demo-prices |
| trend | 0.10 | 0.6000 | +3.00 | demo-prices |
| volume_confirmation | 0.10 | 0.4000 | +2.00 | demo-prices |
| profitability | 0.15 | 0.6000 | +4.50 | demo-fundamentals |
| growth | 0.10 | 0.6000 | +3.00 | demo-fundamentals |
| leverage | 0.10 | 0.6000 | +3.00 | demo-fundamentals |
| valuation | 0.10 | 0.4000 | +2.00 | demo-fundamentals |
| news | 0.10 | 0.6000 | +3.00 | demo-news |
| announcements | 0.10 | 0.7000 | +3.50 | demo-announcements |

## NSE:SIM-FERN

- Supporting: momentum: +6.00 score points (momentum\_20d=0.08)
- Supporting: leverage: +3.00 score points (debt\_to\_equity=0.4)
- Supporting: trend: +3.00 score points (trend\_50d=0.06)
- Counterargument / blocker: Missing or stale factors: -8.25 points
- Counterargument / blocker: Volatility penalty: -1.00 points
- Counterargument / blocker: Factor coverage below the configured minimum
- Data issue: profitability: roce: missing
- Data issue: growth: revenue\_growth\_yoy: missing
- Data issue: valuation: pe\_to\_sector\_median: missing
- Data issue: news: news\_sentiment: missing
- Data issue: announcements: announcement\_impact: missing

| Factor | Weight | Normalized | Points | Sources |
| --- | ---: | ---: | ---: | --- |
| momentum | 0.15 | 0.8000 | +6.00 | demo-prices |
| trend | 0.10 | 0.6000 | +3.00 | demo-prices |
| volume_confirmation | 0.10 | 0.4000 | +2.00 | demo-prices |
| profitability | 0.15 | missing | +0.00 |  |
| growth | 0.10 | missing | +0.00 |  |
| leverage | 0.10 | 0.6000 | +3.00 | demo-fundamentals |
| valuation | 0.10 | missing | +0.00 |  |
| news | 0.10 | missing | +0.00 |  |
| announcements | 0.10 | missing | +0.00 |  |

## Sources

- **demo-announcements**: Fictional announcement fixture; not a real source; available 2026-10-07T06:00:00Z; fixture://oraculum/demo-announcements
- **demo-fundamentals**: Fictional fundamentals fixture; not a real source; available 2026-08-12T04:30:00Z; fixture://oraculum/demo-fundamentals
- **demo-news**: Fictional news fixture; not a real source; available 2026-10-08T06:00:00Z; fixture://oraculum/demo-news
- **demo-prices**: Fictional prices fixture; not a real source; available 2026-10-09T10:05:00Z; fixture://oraculum/demo-prices

## Limitations

- This is an untrained research baseline, not a probability or expected-return forecast.
- Candidates are paper-research signals; no trading or brokerage integration exists.
- Source timestamps are checked as supplied; vendor truth and historical vintages require independent verification.
- The exchange session calendar and universe membership must come from the provider.
- Correlated factors can double-count information; weights and thresholds are research hypotheses.
- Missing data is penalized; coverage measures completeness, not predictive confidence.
- All instruments and figures in this run are fictional fixtures.
