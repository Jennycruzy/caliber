# G3 — Agentic Wallet POLY_1271 order signing — PARTIAL

Date: 2026-07-23
Status: **SIGNING CONFIRMED; REST/CANCEL BLOCKED BY ZERO ALLOWANCE**

## What was tested

The active OKX Agentic Wallet session for owner
`0x48ddC64e362e337b1eaEA67486A9F8c2869eAF38` signed a live Polymarket v2
POLY_1271 order non-interactively. The order used deposit wallet
`0x577108052c8D862984B724668E2f6035Eb6Fa5c5`, signature type `3`, and the
official SDK's ERC-7739 envelope.

The certification order was a post-only BUY:

- price: `0.02 pUSD`
- size: `5.0` outcome tokens
- maker amount: `100000` pUSD base units (`0.1 pUSD`)
- order type: `GTC`
- post-only: `true`

No signature, API secret, passphrase, HMAC, private key, or complete signed body
is recorded here.

## Result

The local equivalence test showed that the external Agentic Wallet adapter
produces the exact same ERC-7739 envelope bytes as the official v2 SDK's
private-key implementation for the same key and order.

The live wallet signed successfully with no browser or human confirmation.
Polymarket then parsed and authenticated the submitted order and rejected it at
the collateral authorization check:

`not enough balance / allowance: the allowance is not enough -> spender:
0xE111180000d2663C0091e4f400237545B87B996B, allowance: 0, sum of matched
orders: 0, order amount (inc. fees): 100000`

This advances the previous signer mismatch: the venue reached the precise
allowance check for the correct Exchange V2 spender and required amount.

## Interpretation

- [x] non-interactive Agentic Wallet EIP-712 signing
- [x] POLY_1271 nested `TypedDataSign` digest
- [x] official ERC-7739 envelope equivalence
- [x] Agentic Wallet L2 credentials and HMAC accepted far enough to evaluate the
  order's collateral authorization
- [x] correct maker/signer deposit-wallet relationship
- [ ] non-zero Exchange V2 allowance
- [ ] accepted resting order and order ID
- [ ] autonomous cancellation
- [ ] BUY fill
- [ ] signed SELL
- [ ] take-profit, stop-loss, invalidation, and time exits

Depositing pUSD and approving Exchange V2 are independent operations. The
deposit wallet still holds pUSD, but its Exchange V2 allowance was zero during
this run. No order rested or filled, so there was nothing to cancel or sell.
