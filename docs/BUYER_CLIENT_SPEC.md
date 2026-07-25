# TrueOdds ASP — Buyer Client Specification

Last updated: 2026-07-24. This is the current buyer-side contract.

## Boundary

TrueOdds sells signals, prepares and validates intents, and relays buyer-signed
Polymarket bytes. It never holds a buyer key, fund, wallet session, L2 secret,
signature, HMAC, or complete signed body.

```text
buyer EOA → setup_buyer_deposit_wallet() → fund deposit wallet
    → local sign (POLY_1271) → TrueOdds submit-signed → Polymarket CLOB
```

Production orders use Polymarket signature type `3` (POLY_1271). The deposit
wallet (derived from the buyer's EOA key) is maker/funder; the EOA key signs
through the v2 SDK's ERC-7739 wrapping. Signature type 0 (direct EOA) is
rejected by the Polymarket CLOB — see G4 evidence for details.

## Buyer identity

The canonical identity is the normalized EOA address. TrueOdds maps it to a
random opaque `buyer_id` (`byr_...`) for URLs and stores all signals, intents,
positions, and emergency state under that buyer. The final signed order's
`POLY_ADDRESS` must equal the bound EOA.

The buyer supplies its address when requesting signals:

```json
{"message":"Give me the best Polymarket signals","limit":5,
 "buyer_address":"0x..."}
```

Polymarket execution candidates receive a random buyer-scoped `signal_id`.

## Signal-to-execution lifecycle

Signal discovery and execution are intentionally separate:

1. `GET/POST /v1/signals` returns ranked signals and `signal_id` values.
2. The agent presents the signal and asks the buyer whether to proceed.
3. `POST /v1/executions/prepare-signal` receives `signal_id`, buyer address,
   quantity, and exit policy.
4. TrueOdds verifies ownership and expiration, reruns the oracle evaluation,
   reads the current market and CLOB book, binds the current outcome token, and
   returns `authorization.status=AWAITING_CONFIRMATION`.
5. The confirmation must show quantity, current limit price, maximum pUSD cost,
   executable depth, book age, and the complete exit policy.
6. After explicit buyer confirmation, the buyer client funds/approves as needed,
   signs locally, and posts `submit-signed` with an approval ID.
7. TrueOdds validates the exact signed order, burns its body hash, relays the
   original bytes, and reconciles venue state. Submission is not a fill.

The signal's displayed price is informational only. The fresh book determines
the executable limit price. Expiration is enforced during preparation and again
before signed submission.

## Local signer interface

```text
address() -> str
sign_order(order_eip712) -> str
sign_and_send(tx) -> tx_hash
```

`EoaOrderSubmitter` in `scripts/buyer_client.py` uses the pinned v2 SDK to:

- resolve the POLY_1271 deposit wallet (explicit, from prepared intent, or derived);
- derive L2 credentials locally;
- construct sig-type-3 BUY and SELL orders (deposit wallet = maker, EOA = signer);
- serialize once;
- calculate L2 headers over those exact bytes;
- submit only the base64 body and headers to TrueOdds;
- return an allowlisted sanitized result.

The configured environment is:

```text
/Users/user/trueodds/.venv-spike/bin/python
```

It contains `py_clob_client_v2`.

## Funding and approvals

The buyer owns all funding operations. `setup_buyer_deposit_wallet()` automates
the entire onboarding in a single call:

1. Derive deposit wallet address from buyer's key
2. Deploy the deposit wallet if needed (via relayer)
3. Wrap USDC.e to pUSD on the buyer EOA if needed
4. Transfer pUSD from EOA to deposit wallet (order amount + fee buffer)
5. Approve pUSD from deposit wallet to exchange_v2 (via relayer batch)
6. Approve conditional tokens (setApprovalForAll) for both exchanges (via relayer)
7. Sync the CLOB balance/allowance cache

Supported funding routes to pUSD:

| Asset held by buyer EOA | Route |
|---|---|
| pUSD | no route |
| Polygon USDC.e | wrap to pUSD |
| X Layer USD₮0 | MESON → Polygon USDT → USDC.e → pUSD |
| Polygon USDT/native USDC | bounded DEX swap → USDC.e → pUSD |

The 2.5-token bridge minimum applies only to the tested X Layer USD₮0 route.
The buyer configuration `.env.buyer` references the existing secret file by
path and variable name; it does not copy the key.

## Buyer-scoped emergency control

There is no global kill switch. `cancel_only` is the default and only emergency
mode. Flattening requires a separate future action and explicit authorization.

The buyer signs an EIP-191 control message containing buyer ID, action, timestamp,
nonce, and reason. The authorization expires after five minutes and nonce reuse
is rejected.

```text
POST /v1/buyers/{buyer_id}/emergency-stop
GET  /v1/buyers/{buyer_id}/emergency-status
POST /v1/buyers/{buyer_id}/emergency-clear
POST /v1/buyers/{buyer_id}/emergency-cancel-signed
```

Emergency stop immediately cancels prepared intents and blocks new preparation
or submission. For open venue orders, the buyer client serializes the exact
order-ID list, creates DELETE `/orders` L2 headers locally, and sends those bytes
to `emergency-cancel-signed`. TrueOdds relays them without obtaining credentials.

## Exit policy

Every signal execution must commit:

```json
{
  "take_profit_pct":"25",
  "stop_loss_pct":"15",
  "max_hold_seconds":86400,
  "max_exit_slippage_bps":150,
  "invalidation_rule":"oracle_probability_below_entry_threshold",
  "partial_fill_policy":"protect_filled_quantity"
}
```

The durable position monitor prioritizes kill switch, invalidation, stop loss,
time/close protection, and take profit. It protects confirmed partial fills,
reserves exits idempotently, prevents overselling, and resumes safely after a
restart. Every resulting SELL is signed by the buyer locally.

## Never do

- Never send a private key, seed phrase, CLOB credentials, signature, HMAC, or
  signed body to TrueOdds or put them in logs/chat.
- Never use signature type 0 (direct EOA); Polymarket CLOB rejects it.
- Never use Agentic Wallet execution, hosted Polymarket bridge, or skip the
  deposit wallet setup.
- Never infer a fill from HTTP success; reconcile confirmed cumulative fills.
