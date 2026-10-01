# Changes

## 0.1.4 — 2026-10-01

- Sync the complete ChatGPT cloud skill download without changing its runtime files.
- Add FinancialJuice, Walter Bloomberg and First Squawk XML discovery feeds; switch the three publisher feeds and Trump RSS to bounded curl transport.
- Correct First Squawk timestamps by 540 minutes once and preserve raw timestamps, undated candidates and titleless items.
- Reuse per-invocation collection outcomes and preserve independent source successes without immediate retries.

Validation: all 41 cloud-packaged tests passed. The release asset is the original cloud ZIP; installed and repository file contents match it. No live connector or feed acceptance is claimed.

## 0.1.1 — 2026-09-26

- Add original Alpaca → Alpaca Paper Trading read-only market-data fallback, preserving later providers and evidence gates.
- Preserve actual connector, request, feed, timestamps and failures. No paper orders, account changes or account-P/L substitution.
- Add capability and response-shape guidance for the observed Paper Trading data wrapper.
- Normalize hosted skill visibility to CHAT/CODEX.

Validation: 36 tests passed. Paper market clock and SPY snapshot read smoke checks passed.
