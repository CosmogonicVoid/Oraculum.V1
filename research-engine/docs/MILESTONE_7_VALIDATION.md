# Milestone 7 validation — 19 October 2026 (IST)

## Scope

The release was checked in Linux with Python, HTTP requests to its local
server and actual local Ollama inference. Native Windows execution and browser
visual rendering were not available. Windows command files were inspected,
the new setup script uses CRLF, and existing launch scripts remain byte-identical
to 0.6.0. Hardware performance on the user's PC has not been measured.

## Automated regressions

**433 tests pass**, including 59 new AI tests and 374 existing regressions.
The suite covers source and report cutoffs; missing and future evidence;
source identity conflicts; strict JSON and role-restricted model selections;
comparisons and abstention; immutable packet/receipt checks; caching, retries,
model-digest changes, interruptions and budgets; nonfatal daily integration;
read-only HTTP routes; escaped untrusted content; local-only transport,
proxies, redirects, response size limits and hard timeouts.

The same suite is run after applying the update ZIP to a fresh 0.6.0 tree.
The upgraded source is compared byte-for-byte with the full release, except
the full-release manifest. ZIP CRCs, file paths, original database digest and
the data-free GitHub source export are checked during packaging.

## Actual local-model checks

Tested runtime: **Ollama 0.40.6**. Model: **qwen3.5:2b**, 1.9B parameters,
Q8_0, 2,683,396,812 bytes. Model digest:

`0689d44085e06d165161a8a9a1731344278cfb5aade63a3c3dbdb48ab54b130a`

The final evidence-selection contract passes all three fictional development
cases: mandatory abstention with missing evidence, favorable-price/adverse-loss
comparison with negative captured-event tone, and ignoring instructions
embedded in publisher text. These cases helped develop the implementation;
they are not a held-out benchmark, broad prompt-injection certification or a
measure of investment accuracy.

Earlier freeform experiments produced unsupported financial statements.
Earlier identifier-selection variants omitted comparisons or reversed their
roles. The released contract therefore accepts no model-written financial
prose and uses named, role-restricted comparison fields. When favorable and
cautionary evidence coexist, the generation schema requires a comparison;
packets with inadequate evidence require abstention. Application text says
to review the two observations together, without asserting causality.

The live integration uses retained public evidence from the 0.6.0 validation
cache, not a fresh market download. Saved report:

`b9530de56460f7af6788986aa756b332279b8ebb3fd3cf8134619778e8cf2fa4`

Price session: **2026-10-16**. Evidence cutoff:
**2026-10-17T19:31:36.105166Z**. AI generation happens later and remains labelled
separately. SKYGOLD and CUPID exercise two captured-evidence notebooks; they
are test examples, not buy recommendations. The cache has only 15 complete
combined-ranking candidates, so this check is not broad market coverage.

Both real-cache selections passed the released validation contract. Generation
in this environment took 19.47 seconds for SKYGOLD and 17.47 seconds for CUPID;
the cached repeat took 0.12 seconds without another inference. The journal
audit passed with two packets and four start/finish records. These timings are
observations from this environment, not a Windows performance promise.

## Preservation and remaining risks

The release checks read-only pages and their internal links, navigation,
headings and labelled GET forms. Before/after hashes verify that viewing
pages and exports does not alter runtime files. Saved research and virtual
paper status are compared with their direct API results.

Ranking, financial calculation, forward-paper policy, research history,
scheduling and the earlier local-AI implementation remain byte-identical to
0.6.0. New AI modules do not send orders or change score weights.

Exact evidence references prevent unrestricted invented narrative from being
accepted; they do not guarantee relevance, correct event tone, complete
coverage, source truth or useful predictions. Source excerpts can themselves
be incomplete or misleading. Required cautions remain visible independently
of what the model selects. Broader model evaluation, better data coverage and
real forward observations remain milestones 8 and 9.
