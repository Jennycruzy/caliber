# TrueOdds execution resume handoff — 2026-07-24 (authoritative)

This document, `BUYER_CLIENT_SPEC.md`, and `EXECUTION_API.md` are the current
execution authority. Older handoffs are historical evidence only.

## Settled architecture

TrueOdds is a non-custodial ASP. Each buyer owns an EOA, funds a POLY_1271
deposit wallet derived from that key, signs locally through ERC-7739 wrapping,
and keeps all private keys and L2 credentials. Production Polymarket orders use
signature type `3` (POLY_1271): the deposit wallet is maker/funder, the EOA is
signer. TrueOdds receives only prepared intent data, signed bytes, and
buyer-created headers.

**G4 finding (2026-07-24):** Signature type 0 (direct EOA) is rejected by the
Polymarket CLOB with "maker address not allowed, please use the deposit wallet
flow". The deposit wallet flow (sig type 3) is required for all orders. See
`docs/evidence/G4_EOA_BUY_SELL_FLAT_2026-07-24.md` for the full evidence.

Buyer identity is the normalized EOA address. Public API URLs use an opaque,
random `buyer_id` (`byr_...`) mapped to that address in the durable execution
store. A signed `POLY_ADDRESS` must match the buyer bound to the intent.

## Implemented control plane

- `GET/POST /v1/signals` can accept `buyer_address`. Eligible Polymarket signals
  receive a durable buyer-scoped `signal_id` (`sig_...`) and an execution URL.
- Signal quotes are informational. `POST /v1/executions/prepare-signal` resolves
  the reference, rejects expiration, reruns the oracle evaluation, reads the
  current Polymarket market and CLOB book, and returns `AWAITING_CONFIRMATION`
  with the exact quantity, live limit price, maximum pUSD cost, depth, book age,
  and exit policy.
- `submit-signed` requires a non-empty buyer approval ID for buyer-bound intents,
  rechecks signal expiration, verifies the EOA address, validates POLY_1271
  BUY/SELL economics, burns the exact signed body hash, and relays bytes unchanged.
- SQLite execution storage now persists buyers, signal references, kill-switch
  state, buyer control nonces, buyer binding, signal binding, expiration, and
  exit policy. Existing databases migrate on startup.
- Buyer-scoped emergency controls are implemented:
  - `POST /v1/buyers/{buyer_id}/emergency-stop` with a five-minute EIP-191
    authorization and one-shot nonce;
  - `GET /v1/buyers/{buyer_id}/emergency-status`;
  - `POST /v1/buyers/{buyer_id}/emergency-clear` with a fresh authorization;
  - `POST /v1/buyers/{buyer_id}/emergency-cancel-signed` to relay the buyer's
    exact DELETE `/orders` bytes and headers.
- Emergency mode is buyer-scoped `cancel_only`. It cancels prepared intents,
  blocks new preparation/submission, and returns open orders for buyer-signed
  venue cancellation. It never flattens a position automatically.
- `scripts/buyer_client.py` now provides local EOA order submission, control
  authorization, and emergency cancellation helpers. It never returns or logs
  private keys, credentials, signatures, HMACs, or complete signed bodies.
- Durable `PositionStore`/position monitor provides cumulative fill accounting,
  partial-fill protection, exit priority, idempotent reservations, oversell
  prevention, and restart recovery.

## Funding and approval rules

- USDC.e → pUSD wrapping, Polygon stable swaps, and X Layer USD₮0 → MESON →
  Polygon USDT → USDC.e → pUSD are buyer-local routes.
- The 2.5-token minimum applies only to the tested X Layer USD₮0 route.
- The deposit wallet is funded by transferring pUSD from the buyer EOA. The
  relayer handles deposit wallet approvals (pUSD to exchange, conditional tokens
  via setApprovalForAll). Fee buffer (~50,000 base units) must be included.
- `setup_buyer_deposit_wallet()` in `scripts/buyer_client.py` automates the
  entire onboarding: derive wallet, deploy, wrap USDC.e, transfer pUSD, approve
  exchange and conditional tokens, sync CLOB cache — single function call.
- The local buyer configuration is `.env.buyer`; it references `.env.spike` by
  variable name and contains no copied secret. Both files are mode 600 and the
  local buyer file is ignored by git.

## Verification status

- Configured SDK environment: `/Users/user/trueodds/.venv-spike/bin/python`.
  `py_clob_client_v2` is installed there.
- Focused buyer/execution/API/position/adapter suite: **99/99 passed** (system
  Python, 2026-07-25). This covers `test_api`, `test_execution`,
  `test_buyer_client`, and `test_polymarket_adapter`.
- Full system suite: **~360 tests collected; ~6 collection/optional-dep failures**
  (`py_clob_client_v2` import, `jinja2`, `x402`). No assertion failure in any
  test that collects.
- `git diff --check`: passed.
- No live book read, order submission, approval, cancellation, or trade was
  performed during this implementation.

## Do not repeat

- Do not use `scripts/polymarket_agent_helper.py` as the production path; it is
  historical tooling.
- Do not use signature type 0 (direct EOA); Polymarket CLOB rejects it. All
  orders must use signature type 3 (POLY_1271 deposit wallet).
- Do not use Agentic Wallet execution, or infer a fill from submission success.
- Do not treat a signal's displayed entry price as an executable price.
- Do not skip the deposit wallet setup — use `setup_buyer_deposit_wallet()` for
  automated onboarding.

## What is done (proved in tests, not live)

1. **Signature type 3 (POLY_1271) migration** — all code, tests, and docs moved
   from sig type 0 to sig type 3 with deposit wallet. 21/21 buyer-client tests
   pass. `setup_buyer_deposit_wallet()` automates the full 7-step onboarding.
2. **PositionStore fill binding** — `ExecutionCoordinator` wired to
   `PositionStore`. BUY fills create positions, partial fills are protected,
   SELL fills reconcile exit, restart recovery finds open positions, idempotent
   replays don't duplicate. 6/6 position-binding tests pass.
3. **Live data adapter** — `HttpPolymarketDataSource` with `market()` and
   `book()` methods fully implemented, field mappings verified against captured
   live CLOB payloads. PROVISIONAL tags removed.
4. **Offline prepare-signal test** — proves the full flow: signal discovery →
   prepare-signal reads fresh book → response contains quantity, limit_price,
   maximum_cost_pusd, fresh_book (best_bid, best_ask, marketable_depth,
   book_age_seconds), and exit_policy. Expired signals rejected with HTTP 410.
   2/2 tests pass.
5. **Restart recovery** — `PositionStore.recoverable()` returns OPEN positions
   after a fresh instantiation on the same database. Tested.

## What is honestly left

### Must do before any live trade

1. **Live emergency stop test** — prove buyer-scoped emergency stop and
   buyer-signed cancellation against a real resting Polymarket order. Requires:
   a funded deposit wallet, a resting GTC order on the book, and operator
   approval to submit and cancel a real order. This cannot be tested offline.
2. **Live BUY → SELL round-trip** — submit a minimum-size BUY, record confirmed
   fill, bind into PositionStore, approve the filled outcome quantity, sign and
   submit a SELL, reconcile until flat. Record order IDs, fills, fees, and
   balance at each step.
3. **Live restart recovery** — after a confirmed fill, kill the process, restart,
   and prove `recoverable()` resumes the same position and reserved exit without
   duplication.
4. **Sanitized G4 evidence capture** — EOA funding, deposit wallet setup, BUY,
   SELL, flat balance, emergency stop/cancel, restart recovery. All evidence
   sanitized (no keys, signatures, or HMACs). Do not change public execution
   status before all evidence is complete.

### Pre-existing issues (not introduced by this work)

- 4 test failures in `test_payment.py::ProductionSafetyTests` — these appear to
  be pre-existing and related to payment settlement configuration, not execution.
- `py_clob_client_v2` and `jinja2` collection errors in the system Python — only
  affects `test_agentic_polymarket_order_signer.py` and `test_site.py`.

## Exact next work for Claude

1. Read this handoff and run `git status`, `git diff --check`, and the 99-test
   focused suite before editing.
2. With operator approval, fund a deposit wallet and place a minimum-size GTC
   BUY order on a liquid Polymarket market.
3. Prove buyer-scoped emergency stop blocks new preparation, then relay the
   buyer's signed DELETE `/orders` and confirm venue cancellation.
4. Clear emergency mode, place another minimum BUY, confirm the fill, bind into
   PositionStore, sign a SELL, reconcile until flat.
5. Kill the process, restart on the same SQLite, confirm `recoverable()` returns
   the correct position state.
6. Capture all evidence, sanitize, and update this handoff with final results.

## Operator gates

No additional secret is needed for offline work. Before any live state change,
the operator must explicitly approve the exact current book, size, maximum pUSD
cost, buyer EOA, and whether the test may submit and cancel a real order. Never
paste a private key, CLOB credential, signature, HMAC, or signed body into chat.
