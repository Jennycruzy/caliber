"""Caller-signed Polymarket order relay.

The ASP never receives a private key here. A caller signs locally, sends the
exact serialized CLOB body plus caller-computed L2 headers, and this module
checks that the signed order matches the prepared intent before relaying the
original bytes unchanged.
"""
from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Callable

import httpx

from rwoo.execution import ExecutionError, VenueResult, canonical

CLOB_ORDER_URL = "https://clob.polymarket.com/order"
CLOB_CANCEL_ORDERS_URL = "https://clob.polymarket.com/orders"
BASE_UNITS = Decimal("1000000")
REQUIRED_POLY_HEADERS = (
    "POLY_ADDRESS",
    "POLY_API_KEY",
    "POLY_PASSPHRASE",
    "POLY_SIGNATURE",
    "POLY_TIMESTAMP",
)


@dataclass(frozen=True)
class SignedOrderPayload:
    body_bytes: bytes
    body_hash: str
    headers: dict[str, str]
    parsed: dict[str, Any]


@dataclass(frozen=True)
class SignedCancelPayload:
    body_bytes: bytes
    body_hash: str
    headers: dict[str, str]
    order_ids: list[str]


def decode_signed_order(body_base64: str, headers: dict[str, str]) -> SignedOrderPayload:
    try:
        body_bytes = base64.b64decode(body_base64, validate=True)
    except Exception as exc:
        raise ExecutionError("INVALID_EXECUTION", "signed order body must be base64") from exc
    if not body_bytes:
        raise ExecutionError("INVALID_EXECUTION", "signed order body is empty")
    try:
        parsed = json.loads(body_bytes)
    except json.JSONDecodeError as exc:
        raise ExecutionError("INVALID_EXECUTION", "signed order body is not JSON") from exc
    if not isinstance(parsed, dict):
        raise ExecutionError("INVALID_EXECUTION", "signed order body must be a JSON object")
    normalized_headers = {str(k).upper(): str(v) for k, v in headers.items()}
    missing = [name for name in REQUIRED_POLY_HEADERS if not normalized_headers.get(name)]
    if missing:
        raise ExecutionError("INVALID_EXECUTION", f"missing Polymarket headers: {', '.join(missing)}")
    return SignedOrderPayload(
        body_bytes=body_bytes,
        body_hash=hashlib.sha256(body_bytes).hexdigest(),
        headers={name: normalized_headers[name] for name in REQUIRED_POLY_HEADERS},
        parsed=parsed,
    )


def decode_signed_cancel(body_base64: str, headers: dict[str, str]) -> SignedCancelPayload:
    try:
        body_bytes = base64.b64decode(body_base64, validate=True)
        parsed = json.loads(body_bytes)
    except Exception as exc:
        raise ExecutionError("INVALID_EXECUTION", "signed cancellation body is invalid") from exc
    if (
        not isinstance(parsed, list)
        or not parsed
        or any(not isinstance(order_id, str) or not order_id for order_id in parsed)
        or len(set(parsed)) != len(parsed)
    ):
        raise ExecutionError("INVALID_EXECUTION", "signed cancellation must be a unique order-id list")
    normalized_headers = {str(k).upper(): str(v) for k, v in headers.items()}
    missing = [name for name in REQUIRED_POLY_HEADERS if not normalized_headers.get(name)]
    if missing:
        raise ExecutionError("INVALID_EXECUTION", f"missing Polymarket headers: {', '.join(missing)}")
    return SignedCancelPayload(
        body_bytes=body_bytes,
        body_hash=hashlib.sha256(body_bytes).hexdigest(),
        headers={name: normalized_headers[name] for name in REQUIRED_POLY_HEADERS},
        order_ids=parsed,
    )


def validate_signed_order_matches_intent(intent: dict[str, Any], payload: SignedOrderPayload) -> None:
    order = payload.parsed.get("order")
    if not isinstance(order, dict):
        raise ExecutionError("SIGNED_ORDER_MISMATCH", "signed payload is missing order object")
    if str(payload.parsed.get("orderType") or intent.get("time_in_force")) != intent.get("time_in_force"):
        raise ExecutionError("SIGNED_ORDER_MISMATCH", "signed order time_in_force does not match intent")
    _require_equal(order, "tokenId", intent["token_id"])
    # `intent.side` identifies the YES/NO outcome. Existing entry intents are
    # BUYs; a future exit intent can set the distinct `order_side` field.
    side = str(intent.get("order_side") or "BUY").upper()
    if side not in {"BUY", "SELL"}:
        raise ExecutionError("SIGNED_ORDER_MISMATCH", "intent side must be BUY or SELL")
    _require_equal(order, "side", side)
    _require_equal(order, "signatureType", 0)
    maker = str(order.get("maker") or "")
    signer = str(order.get("signer") or "")
    if not maker or maker.lower() != signer.lower():
        raise ExecutionError("SIGNED_ORDER_MISMATCH", "EOA order must use the same maker and signer")
    if not str(order.get("signature") or "").startswith("0x"):
        raise ExecutionError("SIGNED_ORDER_MISMATCH", "signed order is missing a signature")
    price = Decimal(intent["price"])
    quantity = Decimal(intent["quantity"])
    expected_maker = _base_units(price * quantity) if side == "BUY" else _base_units(quantity)
    expected_taker = _base_units(quantity) if side == "BUY" else _base_units(price * quantity)
    _require_equal(order, "makerAmount", expected_maker)
    _require_equal(order, "takerAmount", expected_taker)
    expiration = str(order.get("expiration", "0"))
    if not expiration.isdigit():
        raise ExecutionError("SIGNED_ORDER_MISMATCH", "signed order expiration must be numeric")


def relay_signed_order(payload: SignedOrderPayload, *, post: Callable[..., Any] | None = None) -> VenueResult:
    post = post or _post_to_polymarket
    response = post(CLOB_ORDER_URL, headers=payload.headers, content=payload.body_bytes)
    status_code = getattr(response, "status_code", 200)
    try:
        data = response.json()
    except Exception as exc:
        raise ExecutionError("VENUE_RELAY_FAILED", "Polymarket returned a non-JSON response") from exc
    if status_code >= 500:
        raise RuntimeError(f"Polymarket relay status {status_code}")
    if status_code >= 400 or data.get("success") is False or data.get("error"):
        message = str(data.get("error") or data.get("errorMsg") or f"Polymarket rejected order with HTTP {status_code}")
        return VenueResult(state="REJECTED", message=message)
    order_id = data.get("orderID") or data.get("orderId")
    if not order_id:
        raise ExecutionError("INVALID_VENUE_RESPONSE", "Polymarket accepted response without order id")
    return VenueResult(state="OPEN", venue_order_id=str(order_id), message=str(data.get("status") or "live"))


def relay_signed_cancel(payload: SignedCancelPayload, *, delete: Callable[..., Any] | None = None) -> dict[str, Any]:
    delete = delete or _delete_from_polymarket
    response = delete(
        CLOB_CANCEL_ORDERS_URL, headers=payload.headers, content=payload.body_bytes
    )
    status_code = getattr(response, "status_code", 200)
    try:
        data = response.json()
    except Exception as exc:
        raise ExecutionError("VENUE_RELAY_FAILED", "Polymarket returned a non-JSON cancellation response") from exc
    if status_code >= 500:
        raise RuntimeError(f"Polymarket cancellation relay status {status_code}")
    if status_code >= 400 or data.get("error"):
        raise ExecutionError(
            "VENUE_RELAY_FAILED",
            str(data.get("error") or f"Polymarket rejected cancellation with HTTP {status_code}"),
        )
    return data


def _post_to_polymarket(url: str, *, headers: dict[str, str], content: bytes):
    with httpx.Client(timeout=20) as client:
        return client.post(url, headers=headers, content=content)


def _delete_from_polymarket(url: str, *, headers: dict[str, str], content: bytes):
    with httpx.Client(timeout=20) as client:
        return client.request("DELETE", url, headers=headers, content=content)


def _require_equal(container: dict[str, Any], field: str, expected: Any) -> None:
    if str(container.get(field)) != str(expected):
        raise ExecutionError("SIGNED_ORDER_MISMATCH", f"signed order {field} does not match prepared intent")


def _base_units(amount: Decimal) -> str:
    scaled = amount * BASE_UNITS
    if scaled != scaled.to_integral_value():
        raise ExecutionError("INVALID_EXECUTION", f"{canonical(amount)} does not convert to exact base units")
    return str(int(scaled))
