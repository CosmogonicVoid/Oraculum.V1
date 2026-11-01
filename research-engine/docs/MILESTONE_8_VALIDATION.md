# Milestone 8 validation — 20 October 2026

## Automated checks

**465 tests pass:** the existing 433 regressions plus 32 new operational,
coverage and evaluation tests. Tests use controlled synthetic fixtures rather
than fresh market downloads. They cover:

- Complete, missing, non-finite, boolean, unknown-source and future-dated
  financial inputs; accounting periods; frozen report ages; category filters;
  search, pagination, empty reports and CSV/HTML injection handling.
- Heartbeat renewal, missing/corrupt telemetry, clock mismatch, stale and
  normally stopped writers, nonfatal telemetry permissions and completed-status
  precedence. An actual subprocess is terminated to verify that SQLite releases
  its writer lock and the abandoned activity becomes stale.
- Detailed saved progress and successful publication; persistent provider
  denial cooldown across subsequent runs; per-document failures that allow
  other documents to progress; expiration and legacy retry-state compatibility.
- Read-only Coverage CLI/HTTP, malformed query responses, missing archives,
  report-pinned exports and isolation of fictional model evaluations.
- Eight distinct evaluation cases through deterministic stub outputs, including
  detection of a deliberately incorrect event-tone response.

The full suite also runs on a fresh 0.7.0 extraction after applying the upgrade
ZIP. Packaging checks that the upgraded files match the full release, checks
ZIP CRCs and paths, and preserves the original private database digest:

`ec065b706c4de97f032f25bcc781cb26549d8e90e47af94f6d63f9354501fc05`

## HTTP and preservation

A separate local HTTP verification uses seven synthetic stocks and genuine
application report/filing code paths. One has four evidenced financial inputs;
six are incomplete. This is a test scenario, not a market coverage estimate.

**16 pages and 49 internal links** return successfully. Structural checks cover
one main heading, eight navigation entries, unique element IDs, GET-only forms
and absence of scripts/iframes. All six persisted runtime files have identical
before/after hashes. The saved report returned by the API remains identical to
the original fixture. No downloads or inference occur on page reads.

Scoring, financial formulae, forward-paper policy, scheduling, research history,
the earlier local-AI implementation, and the milestone-7 AI contract/runtime/
journal/generation modules are checked byte-for-byte against 0.7.0. Collection,
progress reporting and the optional evaluation harness change; ranking and
paper decisions do not receive a new formula.

Existing Windows command scripts remain byte-identical. The patch excludes
data and validation directories. The GitHub source ZIP excludes runtime
databases, generated research workspaces, models and credentials. Existing
user data and Qwen configuration are outside the patch.

## Limits

Native Windows/Task Scheduler execution and visual browser rendering were not
available. HTTP/HTML checks do not substitute for those platform checks.
No fresh NSE/provider availability claim is made from synthetic tests. No new
live-model benchmark was run; in particular, Qwen2.5 14B has not been evaluated
here. Run `ai-evaluate --extended` locally to measure its compliance with these
eight development cases. The harness tests are not model-accuracy results.

The three live-model cases documented for milestone 7 remain historical evidence
for that earlier validation, not proof that a different model passes the new
suite. No investment edge, complete market coverage or future performance is
established. Actual forward observations and broader source coverage remain
necessary.
