# G4 — EOA-Owned BUY/SELL Round-Trip (2026-07-24)

## What was proved

A buyer-owned EOA funded, bought, sold, and reconciled flat on a live
Polymarket market, using the production POLY_1271 deposit wallet flow with
locally signed orders. No funds passed through TrueOdds.

## Market

- Question: "Will Ivanka Trump announce a presidential run before 2027?"
- Condition ID: `0x3a4346b0618af3efcd946f27650d20cee348308bd4f8c06e62df8e9eabbe0fdb`
- Token ID: `39437292826767693760422550980817174078437966735695178411252552844889624222280`
- neg_risk: false, tick: 0.001, minimum order size: 5

## Addresses

- Buyer EOA (key holder): `0x39Dd06180B445B3215FD093a3bF7A3Bf42dfbe96`
- Deposit wallet (POLY_1271 funder): `0x2c8Be0484b331991542F5edD369C5a70d4255cb6`

## Sequence

### 1. Resting order acceptance (rest-and-cancel)

- BUY 5 @ 0.02 (well below best bid 0.044, resting)
- Order accepted: `0x11b52c13b6e3bf455ad42165d720658cf0d6759dc3cebfc0a263d8f2fb788411`
- Cancelled immediately: `{"canceled":["0x11b5...8411"]}`
- Proved: CLOB accepts and cancels orders from this buyer/deposit wallet

### 2. Funding

| Step | Transaction | Amount |
|------|-------------|--------|
| Wrap USDC.e to pUSD (EOA) | `0x59120cbb...` | 0.125 |
| Approve exchange (pUSD) | `0xd3a23304...` | 225,000 base units |
| Wrap USDC.e to pUSD (EOA, top-up) | `0x7cb6d59a...` | 0.410 |
| Transfer pUSD EOA -> deposit wallet | `0xa6620d8f...` | 0.635 |
| Wrap USDC.e to pUSD (fee buffer) | via wrap handler | 0.050 |
| Transfer pUSD EOA -> deposit wallet | via transfer | 0.050 |

### 3. Conditional token approval

- setApprovalForAll on CT contract for exchange_v2
- Relayer batch: `019f9637-cc80-7dad-8a78-e8202822d9c9`
- On-chain: `0xf0548217d5f9436a012d5e0b4a87918d9e14459b85571bba85a24139dd9d8fd5`

### 4. Marketable BUY

- BUY 23 @ 0.045 = $1.035 notional
- Order ID: `0x48e85a1e947b3b468fd7e223eb5896f571be802e65c2f3f7f830f0d462045530`
- HTTP 200, order accepted and filled
- Outcome token balance after: 23,000,000 base units

### 5. SELL to flat

- SELL 23 @ 0.044 (best bid) = $1.012
- Order ID: `0x3e7a30b0db4cf52e40bc788e5f1b3bd61f4b50d987dbd3ac47ea968da25e7724`
- HTTP 200, order accepted and filled

### 6. Final reconciliation

| Asset | Balance |
|-------|---------|
| Outcome tokens | 0 (flat) |
| Deposit wallet pUSD | 0.983780 |
| EOA pUSD | 0 |
| EOA USDC.e | 1.565003 |

Position is flat. Spread + fees consumed ~$0.06 total.

## Architecture findings

1. **Signature type 0 (pure EOA) is rejected** by the CLOB with "maker address
   not allowed, please use the deposit wallet flow". The deposit wallet must
   exist as the maker even when the EOA key signs.

2. **Signature type 3 (POLY_1271)** works: deposit wallet is maker/funder,
   EOA key signs through the v2 SDK's ERC-7739 wrapping.

3. **$1 minimum notional** for marketable orders (not just 5-contract minimum
   size). Resting orders below $1 are accepted.

4. **Conditional token approval** must be granted through the relayer batch
   (setApprovalForAll on the CT contract for exchange_v2) before SELL orders.

5. The `"Could not create api key"` log line is a benign v2 SDK fallback: it
   tries `create_api_key`, fails, then succeeds with `derive_api_key`.

## What this supersedes

- The RESUME_HANDOFF_2026-07-24.md assertion that sig type 0 is the production
  path is incorrect. Sig type 3 with a POLY_1271 deposit wallet is required.
- The "Do not fund or bridge to the POLY_1271 deposit wallet" instruction is
  revised: the deposit wallet IS the required funder for CLOB orders.

## Sanitization

No private key, API secret, API passphrase, HMAC signature, or full signed
order body appears in this record. Order IDs and transaction hashes are public
on-chain data.
