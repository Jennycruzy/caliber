# G1 — OKX Agentic Wallet X Layer bridge (partial)

Date: 2026-07-23

## Result

Partial success only. The OKX Agentic Wallet autonomously approved and submitted
an X Layer USD₮0 bridge transaction through the OKX/MESON route. The source
transaction succeeded and 2.5 USD₮0 left the wallet, but destination settlement
and pUSD credit on Polygon have not yet been observed. Do not mark the backend
`executable` and do not send another bridge transaction until this transfer is
resolved.

## Wallet and route

- Login identity: `kingsjanet0@gmail.com`
- Owner EVM/X Layer wallet: `0x48ddC64e362e337b1eaEA67486A9F8c2869eAF38`
- Beacon-derived Polymarket deposit wallet:
  `0x577108052c8D862984B724668E2f6035Eb6Fa5c5`
- Polymarket bridge receiver:
  `0xf4689cc91e2b2295d31d3c66d548f3e413c9cef2`
- Source: X Layer USD₮0
  `0x779ded0c9e1022225f8e0630b35a9b54be713736`
- Route: X Layer USD₮0 -> Polygon USDT, MESON bridge ID `223`
- Input: `2.5` USD₮0
- Quoted output/minimum output: `2.4` USDT
- Quoted fee: `0.1` USDT
- Geoblock check: `{"blocked":false}`

The receiver intentionally differs from the sender: it is the verified,
beacon-derived Polymarket deposit address for this owner. It was not an arbitrary
destination.

## Direct execute limitation

Both the direct cross-chain execute call and the unsigned cross-chain builder
rejected the Agentic Wallet address with API code `82110`:
`not support AA wallet address`.

Same-chain Agentic Wallet swaps worked, showing this is specific to the
cross-chain builder/execute address validation rather than a general inability
to execute transactions.

## Autonomous workaround exercised

The route was built using a plain EOA as the builder-only sender parameter. The
returned MESON calldata did not embed that placeholder address. The real
Agentic Wallet then executed the required calls itself with
`wallet contract-call`; the ASP did not receive or custody a key.

1. Exact 2.5 USD₮0 approval to MESON:
   - Agentic Wallet order ID: `1808471368803221568`
   - Transaction:
     `0x897d07d3b836b8d9b3eca56e06e6e8d78eb7e78496df583a60f76d09cf94db17`
   - Wallet history status: `SUCCESS`
2. MESON bridge call:
   - Agentic Wallet order ID: `1808495695498068027`
   - Transaction:
     `0x4008e6a2809071ebf59b6ba238121923a41c411b3ab4c219c46f9906ceb73843`
   - Source-chain wallet history status: `SUCCESS`

Security scans found no actionable approval or bridge-call risk. Before approval,
simulation correctly failed at `transferFrom`; after approval the final scan did
not report that revert.

## Settlement state at handoff

- Repeated cross-chain status checks returned `NOT_FOUND` for the bridge
  transaction.
- Polygon pUSD balance at the deposit wallet remained `0`.
- Final X Layer wallet balances:
  - `1.719665` USD₮0
  - `0.000245` legacy USDT
  - `0.006` OKB

The 2.5 USD₮0 source debit is therefore proven, but successful destination
delivery is not. Treat the funds as in flight or requiring MESON/OKX
investigation. Do not retry: the wallet is also now below the X Layer 2.5-token
route minimum.

## Supporting same-chain tests

- USD₮0 -> legacy X Layer USDT:
  `0xe97020c53c0ebb0974236016a09448aa824497bd4c4cae5575f64edf87e645cb`
- Legacy X Layer USDT -> USD₮0:
  `0x9be7062a6ddd444ef436621942f6f13117e2e6d30bed7f153b8d8ca73afac14f`

Legacy X Layer USDT had no usable MESON liquidity in the tested route. Converting
to legacy USDT first is therefore not the demonstrated workaround.

## Signing progress

`onchainos wallet sign-message --type eip712` successfully signed the
`ClobAuthDomain` payload with the Agentic Wallet. No signature is recorded here.
This proves the EIP-712 primitive, but L2 credential creation, ERC-1271/ERC-7739
compatibility, order acceptance, and cancellation are still unproven.

## Minimum correction

The `2.5` minimum applies to the tested X Layer USDT/USD₮0 bridge path. It must
not be applied globally to normal EVM/Polygon Polymarket deposit routes, which
have no corresponding minimum in this implementation.

