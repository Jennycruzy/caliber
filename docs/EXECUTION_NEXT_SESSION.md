# TrueOdds execution — next session

**Superseded by:** `RESUME_HANDOFF_2026-07-24.md`,
`BUYER_CLIENT_SPEC.md`, and `EXECUTION_API.md`. This file is retained as the
short Claude startup card; all Agentic Wallet/POLY_1271/JIT MaxUint256 guidance
from the older version is historical and must not be followed.

## Current state

The ASP is non-custodial and buyer-scoped:

- buyer-owned EOA;
- Polymarket signature type `0`;
- exact bounded approvals;
- local EOA L2 credential derivation and order signing;
- durable buyer-scoped signal references;
- fresh-book `prepare-signal` confirmation;
- explicit approval before buyer-bound signed submission;
- EOA-address binding on `POLY_ADDRESS`;
- buyer-scoped, EIP-191-authorized `cancel_only` emergency stop;
- buyer-signed exact-byte emergency venue cancellation;
- durable position monitoring and restart recovery.

The signal endpoint does not execute. It returns a `signal_id`; the separate
prepare endpoint resolves it and re-reads the live CLOB book. The displayed
signal price is never treated as an executable price.

## What was verified

- `/Users/user/trueodds/.venv-spike/bin/python` contains `py_clob_client_v2`.
- Configured focused suite: **108/108 passed**.
- Full system suite: **344 total; 338 passed; 6 optional dependency errors**
  (`py_clob_client_v2`, `x402`, and `jinja2` in the system interpreter).
- `git diff --check`: passed.
- No live state-changing execution was performed during the control-plane work.

## Claude’s exact next actions

1. Read the authoritative handoff and inspect `git status`; preserve unrelated
   changes.
2. Run the configured 108-test suite before editing.
3. Verify the production Polymarket adapter is injected with live `market()` and
   `book()` reads, while `RWOO_EXECUTION_MODE=disabled` remains the default.
4. Add tests for stale books, changed best asks, expired signal references,
   buyer mismatch, and duplicate emergency cancellation.
5. Run a no-network end-to-end buyer flow through `prepare-signal`, inspect the
   exact confirmation terms, then exercise type-0 BUY/SELL serialization using
   `.venv-spike`.
6. With explicit operator approval only, re-read the live book and execute the
   minimum size-5 BUY through the buyer EOA. Fund exact current notional and
   approve exact amounts.
7. Bind only confirmed fills into `PositionStore`; protect partial fills,
   locally sign the exact SELL, reconcile flat, and collect sanitized evidence.
8. Test buyer emergency stop and buyer-signed DELETE `/orders` on a real order
   only with explicit approval.
9. Prove restart recovery uses the existing exit reservation, never duplicates.
10. Add G4 evidence and update public execution status only after every gate.

## Operator approval required

Offline coding and tests need no additional secret. Before any live transaction,
the operator must approve the exact buyer EOA, current book, quantity, maximum
pUSD cost, approval amounts, and whether the real order may be submitted and
cancelled. Do not request or paste private key material.
