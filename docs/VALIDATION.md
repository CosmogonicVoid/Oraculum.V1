# Forecast v1 verification

- TypeScript check: passed.
- Production Worker/client build: passed.
- 18 automated checks: passed (original API/account/feed checks plus new model/replay/research tests).
- New local schema migration: applied successfully without modifying existing account tables.
- Forecast audit: RELIANCE snapshots at three replay cutoffs reproduce from only the history available through those cutoffs.
- Recorded outcomes remain unavailable until 20 replay sessions are revealed.
- New API tests execute actual handlers against SQLite, including simultaneous stale actions and separate users.
- Research imports retain original forecast timestamps and detect changed price histories before settlement.
- Browser visual/interaction QA: **unverified**. The managed browser service timed out opening the preview; this is not a claim that the screen or hosted login was tested.
- Actual Windows/macOS installation: not run in this Linux environment. Cross-platform commands and a Windows launcher are included.
- No current-market data provider, brokerage, external LLM, automated daily ingest or predictive-skill claim was tested or configured.

Data sources and hashes: `data/provenance.json`. Limitations and reproducible commands: `README.md`.
