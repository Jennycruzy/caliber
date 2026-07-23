#!/usr/bin/env python3
"""Certify an Agentic Wallet POLY_1271 order with a tiny rest-and-cancel."""
from __future__ import annotations

import argparse
import json
import stat
from pathlib import Path

from py_clob_client_v2 import OrderArgs, OrderType, PartialCreateOrderOptions
from py_clob_client_v2.clob_types import ApiCreds, OrderPayload
from py_clob_client_v2.order_utils.model.order_data_v2 import order_to_json_v2

from agentic_polymarket_order_signer import agentic_clob_client

OWNER = "0x48ddC64e362e337b1eaEA67486A9F8c2869eAF38"
DEPOSIT_WALLET = "0x577108052c8D862984B724668E2f6035Eb6Fa5c5"
HOST = "https://clob.polymarket.com"


def _mode_600_json(path: Path) -> dict:
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        raise SystemExit(f"credential file must be mode 600, got {oct(mode)}")
    return json.loads(path.read_text(encoding="utf-8"))


def _creds(path: Path) -> ApiCreds:
    value = _mode_600_json(path)
    return ApiCreds(
        api_key=value.get("apiKey") or value.get("api_key") or value.get("key"),
        api_secret=value.get("secret") or value.get("api_secret"),
        api_passphrase=value.get("passphrase") or value.get("api_passphrase"),
    )


def _env(path: Path) -> dict[str, str]:
    result = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip().strip("\"'")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--credentials", type=Path, default=Path("/tmp/.trueodds_agentic_creds.json"))
    parser.add_argument("--env-file", type=Path, default=Path(".env.spike"))
    parser.add_argument("--token-id")
    parser.add_argument("--price", type=float)
    parser.add_argument("--size", type=float)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    env = _env(args.env_file)
    token_id = args.token_id or env.get("SPIKE_TOKEN_ID")
    price = args.price if args.price is not None else float(env.get("SPIKE_PRICE", "0.02"))
    size = args.size if args.size is not None else float(env.get("SPIKE_SIZE", "5"))
    if not token_id:
        raise SystemExit("--token-id is required")

    creds = _creds(args.credentials)
    client = agentic_clob_client(
        host=HOST,
        owner=OWNER,
        deposit_wallet=DEPOSIT_WALLET,
        creds=creds,
    )
    tick_size = client.get_tick_size(token_id)
    neg_risk = client.get_neg_risk(token_id)
    order = client.create_order(
        OrderArgs(token_id=token_id, price=price, size=size, side="BUY"),
        PartialCreateOrderOptions(tick_size=tick_size, neg_risk=neg_risk),
    )
    body = order_to_json_v2(order, creds.api_key, OrderType.GTC, True, False)
    print(json.dumps({
        "status": "SIGNED",
        "maker": body["order"]["maker"],
        "signer": body["order"]["signer"],
        "signature_type": body["order"]["signatureType"],
        "side": body["order"]["side"],
        "price": price,
        "size": size,
        "post_only": True,
        "signature_recorded": False,
    }, separators=(",", ":")))
    if not args.execute:
        return

    response = client.post_order(order, OrderType.GTC, post_only=True)
    print(json.dumps({"status": "POST_RESPONSE", "response": response}, separators=(",", ":")))
    order_id = response.get("orderID") or response.get("orderId") or response.get("id")
    if not order_id:
        raise SystemExit("CLOB did not accept the rest order; no order id to cancel")
    cancelled = client.cancel_order(OrderPayload(orderID=order_id))
    print(json.dumps({
        "status": "REST_AND_CANCEL_CONFIRMED",
        "order_id": order_id,
        "cancel_response": cancelled,
    }, separators=(",", ":")))


if __name__ == "__main__":
    main()
