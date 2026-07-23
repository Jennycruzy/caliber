# G0 Polymarket Live Relay Evidence

Run date: 2026-07-23
Evidence recorded: 2026-07-23T09:16:27Z
Command: `.venv-spike/bin/python scripts/g0_spike.py --live`

This artifact records the sanitized result of the funded Variant A spike. It
contains no private key, API secret, passphrase, HMAC, or signed order body.

## Preflight

- Polymarket geoblock API: `blocked=false`
- Caller-owned POLY_1271 deposit wallet:
  `0x2c8Be0484b331991542F5edD369C5a70d4255cb6`
- Collateral: `0.4 pUSD`
- Required order notional: `0.1 pUSD`
- Exchange allowance: sufficient
- Signed body size: `1262` bytes
- Signed body SHA-256 prefix: `6a5b413256346611`

## Acceptance

The byte-identical caller-signed body and caller-created L2 headers were relayed
to `POST https://clob.polymarket.com/order`.

```json
{
  "http_status": 200,
  "response": {
    "errorMsg": "",
    "orderID": "0xc1072646a124d8f7a21f5bdecd214347174cababe943b9864443899a75db05eb",
    "takingAmount": "",
    "makingAmount": "",
    "status": "live",
    "success": true
  }
}
```

Order facts returned by the CLOB:

- Side: `BUY`
- Price: `0.02`
- Original size: `5`
- Matched size: `0`
- Type: `GTC`

## Cancellation

The caller SDK cancelled that exact order ID:

```json
{
  "not_canceled": {},
  "canceled": [
    "0xc1072646a124d8f7a21f5bdecd214347174cababe943b9864443899a75db05eb"
  ]
}
```

A follow-up authenticated order query returned:

```json
{
  "id": "0xc1072646a124d8f7a21f5bdecd214347174cababe943b9864443899a75db05eb",
  "status": "CANCELED",
  "original_size": "5",
  "size_matched": "0",
  "price": "0.02",
  "side": "BUY",
  "associate_trades": []
}
```

## Conclusion

Gate G0 is proven for the local private-key caller backend using
POLY_1271/pUSD/V2: the venue accepted a byte-identical order relayed by a process
holding neither the caller private key nor L2 credentials, and the caller then
cancelled it with no fill.

This does not certify the OKX Agentic Wallet backend. That backend still needs
its own funding, signing, submission, and cancellation proof without exposing a
raw private key.
