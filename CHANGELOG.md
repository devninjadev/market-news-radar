# Changes

## 0.1.1 — 2026-09-26

- Add original Alpaca → Alpaca Paper Trading read-only market-data fallback, preserving later providers and evidence gates.
- Preserve actual connector, request, feed, timestamps and failures. No paper orders, account changes or account-P/L substitution.
- Add capability and response-shape guidance for the observed Paper Trading data wrapper.
- Normalize hosted skill visibility to CHAT/CODEX.

Validation: 36 tests passed. Paper market clock and SPY snapshot read smoke checks passed.
