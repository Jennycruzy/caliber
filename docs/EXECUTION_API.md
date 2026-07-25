# Prediction-Market Execution API

Last reviewed: 2026-07-24

This release adds the durable execution control plane behind the existing
TrueOdd API and does not change Agent #5560 or its marketplace listing.

## What is implemented

- `POST /v1/executions/prepare` creates a receipt-bound, risk-checked limit
  order intent. `Idempotency-Key` is mandatory.
- `POST /v1/executions/prepare-signal` resolves a buyer-scoped `signal_id`,
  rejects expired signals, re-evaluates the oracle decision, reads the live
  Polymarket CLOB book, and returns the exact confirmation terms. The signal's
  original quote is informational and is never reused as an execution price.
- `GET /v1/executions/{intent_id}` returns the current state and complete
  transition history.
- `POST /v1/executions/{intent_id}/submit` is the funded submission boundary.
- `POST /v1/executions/{intent_id}/submit-signed` relays a caller-signed
  Polymarket order without receiving a private key.
- `POST /v1/executions/{intent_id}/cancel` cancels a prepared intent locally or
  delegates an acknowledged order to the venue adapter.
- `POST /v1/buyers/{buyer_id}/emergency-stop` activates a buyer-scoped,
  EOA-signed, replay-protected `cancel_only` kill switch. It cancels prepared
  intents immediately and returns open intents requiring buyer L2 cancellation.
- `POST /v1/buyers/{buyer_id}/emergency-cancel-signed` relays the buyer's exact
  locally authenticated order-ID list to the venue without retaining L2
  credentials.
- `GET /v1/buyers/{buyer_id}/emergency-status` inspects the switch and
  `POST /v1/buyers/{buyer_id}/emergency-clear` clears it with a fresh EOA
  signature.
- `POST /v1/executions/{intent_id}/reconcile` resolves nonterminal and
  ambiguous venue outcomes.

Prices and quantities are decimal strings. They are never accepted as binary
floating-point values. Intents and transitions are committed transactionally
to SQLite in WAL mode before any venue call. A transport timeout after a
submission becomes `UNKNOWN`; it is never treated as a rejection and is never
blindly resubmitted.

Direct preparation requires the hash of an existing actionable `check-market`
receipt. Signal preparation instead requires a buyer-scoped `signal_id`; it
creates the executable binding from a fresh oracle evaluation and live book.
Both paths bind venue, market, event group, and side. The API never accepts a
private key, seed phrase, wallet export, or email OTP.

Prepared and inspected Polymarket intents include `client_execution`, a
machine-readable package for caller agents:

- `target_collateral`: pUSD on Polygon.
- `funding_routes`: the normal autonomous route is X Layer USDT/USDT0 via OKX
  cross-chain into the caller's Polymarket bridge deposit address. Direct pUSD,
  Polygon USDC.e onramp, Polygon native USDC, and Polygon USDT remain
  fallback/setup routes. Every bridge route carries
  `minimum_deposit` (2.5, or 2500000 base units). The bridge credits no pUSD
  below that floor and returns no error, so the floor is published rather than
  left to be discovered; the caller helper sizes every transfer at
  `max(order_notional, minimum)`.
- `wallet_backends`: `local_private_key` is the current buyer-owned EOA backend.
  Agentic Wallet/POLY_1271 is historical and is not a production backend.
- `submit_signed.url`: the ASP relay endpoint for the prepared intent.

The intended caller-agent flow is:

```text
request signals with the buyer EOA
agent presents signal_id and asks for confirmation
prepare-signal reruns the oracle and reads the fresh CLOB book
buyer client funds/approves locally, then signs a type-0 order and headers
buyer client POSTs body_base64 + headers + operator_approval_id
ASP validates intent match + replay guard, then relays byte-identical to CLOB
```

## Best Signals to execution

When `buyer_address` is supplied to `GET/POST /v1/signals`, each
promotion-eligible Polymarket result receives a random durable `signal_id` and
an execution affordance. The reference is scoped to the opaque `buyer_id` for
that EOA and expires with the signal.

The agent presents the signal first. After the buyer chooses it, the agent calls
`POST /v1/executions/prepare-signal` with `signal_id`, quantity, and exit policy.
Preparation performs a new oracle evaluation and a fresh CLOB market/book read,
then returns `authorization.status=AWAITING_CONFIRMATION` with:

- exact quantity;
- live limit price;
- maximum pUSD cost;
- executable depth and book age;
- committed exit policy.

Only after the buyer confirms those terms does the buyer client sign and call
`submit-signed` with a non-empty `operator_approval_id`. The relay additionally
requires `POLY_ADDRESS` to equal the EOA bound to the signal and intent.

Signal discovery and execution remain separate endpoints. Signal retrieval
never spends funds, grants approval, or submits an order.

## Buyer-scoped emergency control

There is no global kill switch. Emergency state is stored per buyer EOA.
`cancel_only` is the sole emergency-stop mode; flattening is intentionally a
different future action requiring separate authorization.

Stop and clear requests use an EIP-191 signature over the buyer ID, action,
timestamp, one-shot nonce, and reason. Authorizations expire after five minutes,
and nonce reuse is rejected. Open-order cancellation headers are created over
the exact serialized order-ID list in the buyer process and relayed
byte-identically through `emergency-cancel-signed`.

`submit-signed` payload:

```json
{
  "body_base64": "<base64 of exact serialized Polymarket /order body>",
  "headers": {
    "POLY_ADDRESS": "<caller address>",
    "POLY_API_KEY": "<caller CLOB api key>",
    "POLY_PASSPHRASE": "<caller CLOB passphrase>",
    "POLY_SIGNATURE": "<caller L2 HMAC>",
    "POLY_TIMESTAMP": "<caller timestamp>"
  }
}
```

The relay validates that the signed order matches the prepared intent:
`tokenId`, BUY/SELL side, `orderType`, maker/taker integer amounts, signature
type `0`, EOA maker/signer shape, buyer `POLY_ADDRESS`, expiration, and
signature presence.
Each accepted body hash is stored before relay so the same signed order can only
be used once.

## Fail-closed configuration

```text
RWOO_EXECUTION_DB_PATH=data/execution/intents.sqlite3
RWOO_EXECUTION_MODE=disabled
RWOO_EXECUTION_MAX_ORDER_USD=10.00
```

`disabled` is the production default. It permits preparation, inspection, and
local cancellation but returns `EXECUTION_DISABLED` for funded submission or
venue reconciliation. Setting `RWOO_EXECUTION_MODE=live` alone is insufficient:
the process must also receive an explicitly constructed venue adapter, so an
environment typo cannot activate trading.

## Remaining live activation work

The control plane is real, not a simulated-fill product, but funded execution
is intentionally not ready for general ASP callers yet. Live activation still
requires:

1. inject and validate the production live Polymarket data/book adapter;
2. run local type-0 BUY/SELL and emergency DELETE `/orders` integration tests;
3. perform the explicitly approved minimum-size buyer EOA test and reconcile
   confirmed fills;
4. connect fill streams/REST reconciliation, startup recovery, and settlement
   accounting;
5. run load, fault-injection, venue test-order, and operator runbook checks.

Until those gates pass, metadata reports `execution_enabled: false`. The
caller-signed relay and buyer-scoped emergency control paths exist, but general
funded execution remains disabled.
