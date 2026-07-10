"""OKX Agent Payments Protocol (x402) — HTTP 402 challenge and verification.

This implements the *flow and the server-side authorization checks*, not a
fabricated cryptographic scheme. An unpaid protected request gets a 402 whose
body is the standard x402 challenge (``x402Version`` + ``accepts``); the client
re-sends the identical request with an ``X-PAYMENT`` header carrying the
scheme-native payment payload. The server then:

  * decodes ``X-PAYMENT`` (base64 JSON) — malformed => PAYMENT_INVALID;
  * checks the binding the challenge demanded — scheme, network (wrong-chain),
    asset (wrong-token), recipient (wrong-recipient), amount (insufficient),
    expiry (expired), and the per-request commitment (request hash + service);
  * rejects a replayed nonce => PAYMENT_REPLAYED;
  * delegates the actual cryptographic settlement/verification to an injected
    :class:`PaymentVerifier`. The real EVM/facilitator authorization inside
    ``payload`` is NOT re-implemented or faked here — that is the facilitator's
    job, and its exact schema must match the official OKX/x402 ``exact`` scheme.

Design guarantees:
  * No buyer private key is ever accepted, logged, or stored.
  * Prices, asset, network, decimals, and recipient come only from config;
    nothing is hardcoded and no default asset is assumed.
  * A development stub verifier cannot run in a production environment.
  * When payments are enabled but the settlement path is not fully configured,
    the gate fails CLOSED — a paid endpoint is never served for free.
"""
from __future__ import annotations

import base64
import binascii
import json
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

# --- protocol literals (used exactly; do not rename) ---
X402_VERSION = 1
X_PAYMENT_HEADER = "X-PAYMENT"
PAYMENT_SIGNATURE_HEADER = "PAYMENT-SIGNATURE"
PAYMENT_RESPONSE_HEADER = "PAYMENT-RESPONSE"
WWW_AUTHENTICATE_VALUE = "Payment"
PAYMENT_REQUIRED_ERROR = "PAYMENT-REQUIRED"
DEFAULT_SCHEME = "exact"

# service identifier -> env var holding its price in atomic token units
_PRICE_ENV = {
    "rwoo.check_market": "RWOO_PRICE_CHECK_MARKET",
    "rwoo.cross_venue_edge": "RWOO_PRICE_CROSS_VENUE",
}


def _env(name: str) -> str | None:
    value = os.environ.get(name)
    return value if value not in (None, "") else None


@dataclass(frozen=True)
class PaymentConfig:
    """All values come from the environment; every economic value defaults to
    None so an unconfigured deployment cannot transact."""

    enabled: bool = False
    mode: str = "disabled"  # "disabled" | "stub" | "facilitator"
    environment: str = "development"
    scheme: str = DEFAULT_SCHEME
    network: str | None = None
    asset: str | None = None
    asset_name: str | None = None
    asset_decimals: int | None = None
    recipient: str | None = None
    facilitator_url: str | None = None
    max_timeout_seconds: int = 300
    prices: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> "PaymentConfig":
        enabled = (_env("RWOO_PAYMENT_ENABLED") or "false").lower() in {"1", "true", "yes", "on"}
        mode = (_env("RWOO_PAYMENT_MODE") or ("disabled" if not enabled else "facilitator")).lower()
        decimals = _env("RWOO_PAYMENT_ASSET_DECIMALS")
        prices = {svc: _env(var) for svc, var in _PRICE_ENV.items() if _env(var) is not None}
        return cls(
            enabled=enabled,
            mode=mode,
            environment=(_env("RWOO_ENV") or "development").lower(),
            scheme=_env("RWOO_PAYMENT_SCHEME") or DEFAULT_SCHEME,
            network=_env("RWOO_PAYMENT_NETWORK"),
            asset=_env("RWOO_PAYMENT_ASSET"),
            asset_name=_env("RWOO_PAYMENT_ASSET_NAME"),
            asset_decimals=int(decimals) if decimals and decimals.isdigit() else None,
            recipient=_env("RWOO_PAYMENT_RECIPIENT"),
            facilitator_url=_env("RWOO_PAYMENT_FACILITATOR_URL"),
            max_timeout_seconds=int(_env("RWOO_PAYMENT_MAX_TIMEOUT_SECONDS") or "300"),
            prices=prices,
        )

    @property
    def is_production(self) -> bool:
        return self.environment in {"production", "prod"}

    def price_for(self, service: str) -> str | None:
        return self.prices.get(service)

    def settlement_readiness(self) -> tuple[bool, list[str]]:
        """What is still missing before a live paid call can settle."""
        missing: list[str] = []
        if not self.network:
            missing.append("RWOO_PAYMENT_NETWORK")
        if not self.asset:
            missing.append("RWOO_PAYMENT_ASSET")
        if self.asset_decimals is None:
            missing.append("RWOO_PAYMENT_ASSET_DECIMALS")
        if not self.recipient:
            missing.append("RWOO_PAYMENT_RECIPIENT")
        if self.mode == "facilitator" and not self.facilitator_url:
            missing.append("RWOO_PAYMENT_FACILITATOR_URL")
        for service in _PRICE_ENV:
            if self.price_for(service) is None:
                missing.append(_PRICE_ENV[service])
        return (not missing, missing)


class PaymentError(Exception):
    """A payment rejection with a stable code (PAYMENT_INVALID / _REPLAYED)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class PaymentRequired(Exception):
    """Raised to signal an unpaid protected request; carries the 402 challenge
    body and the headers the transport must attach."""

    def __init__(self, challenge: dict[str, Any]) -> None:
        super().__init__("payment required")
        self.challenge = challenge
        self.headers = {"WWW-Authenticate": WWW_AUTHENTICATE_VALUE}


@dataclass(frozen=True)
class VerificationResult:
    success: bool
    payment_reference: str | None = None
    settlement: dict[str, Any] | None = None


# ------------------------------ verifiers ---------------------------------


class PaymentVerifier(Protocol):
    def verify(self, config: PaymentConfig, service: str, resource: str,
               request_hash: str, payment: dict[str, Any]) -> VerificationResult: ...


class DisabledVerifier:
    """Never authorizes. Used when the settlement path is not configured, so a
    paid endpoint fails closed instead of being served for free."""

    def verify(self, config, service, resource, request_hash, payment) -> VerificationResult:
        raise PaymentError("PAYMENT_INVALID", "payment verification is not configured")


class StubVerifier:
    """Development/test only. Authorizes a payment whose payload carries the
    explicit marker ``{"stub_authorized": true}``. Constructing one in a
    production environment is refused, so it cannot be reached by accident."""

    def __init__(self, environment: str) -> None:
        if environment in {"production", "prod"}:
            raise RuntimeError("StubVerifier must never be enabled in production")

    def verify(self, config, service, resource, request_hash, payment) -> VerificationResult:
        inner = payment.get("payload") or {}
        if inner.get("stub_authorized") is not True:
            raise PaymentError("PAYMENT_INVALID", "stub payment payload is not authorized")
        return VerificationResult(
            success=True,
            payment_reference=f"stub:{inner.get('nonce')}",
            settlement={"mode": "stub", "nonce": inner.get("nonce"), "network": config.network},
        )


class FacilitatorVerifier:
    """Live verification via the operator-configured OKX/x402 facilitator.

    Structurally implemented but intentionally not exercised without an
    operator-approved facilitator URL, recipient, asset, and network. The exact
    request/response schema MUST be confirmed against official OKX Agent
    Payments documentation before this path is enabled in production.
    """

    def __init__(self, config: PaymentConfig) -> None:
        if not config.facilitator_url:
            raise RuntimeError("facilitator mode requires RWOO_PAYMENT_FACILITATOR_URL")
        self.facilitator_url = config.facilitator_url.rstrip("/")

    def verify(self, config, service, resource, request_hash, payment) -> VerificationResult:
        import httpx

        body = {
            "x402Version": X402_VERSION,
            "scheme": config.scheme,
            "network": config.network,
            "resource": resource,
            "payTo": config.recipient,
            "asset": config.asset,
            "maxAmountRequired": config.price_for(service),
            "payment": payment,
        }
        try:
            resp = httpx.post(f"{self.facilitator_url}/verify", json=body, timeout=20)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as exc:  # do not leak facilitator internals
            raise PaymentError("PAYMENT_INVALID", "facilitator could not verify the payment") from exc
        if not data.get("isValid") and not data.get("valid"):
            raise PaymentError("PAYMENT_INVALID", str(data.get("invalidReason") or "payment rejected"))
        return VerificationResult(
            success=True,
            payment_reference=str(data.get("txHash") or data.get("payment_reference") or ""),
            settlement={"mode": "facilitator", "network": config.network, "response": data},
        )


def select_verifier(config: PaymentConfig) -> PaymentVerifier:
    if not config.enabled or config.mode == "disabled":
        return DisabledVerifier()
    if config.mode == "stub":
        return StubVerifier(config.environment)  # raises in production
    if config.mode == "facilitator":
        return FacilitatorVerifier(config)
    raise RuntimeError(f"unknown RWOO_PAYMENT_MODE {config.mode!r}")


def validate_startup(config: PaymentConfig) -> None:
    """Fail closed at boot if payments are enabled but unsafe/incomplete."""
    if not config.enabled:
        return
    if config.mode == "stub" and config.is_production:
        raise RuntimeError("RWOO_PAYMENT_MODE=stub is refused in production")
    ready, missing = config.settlement_readiness()
    if not ready:
        raise RuntimeError(
            "payments enabled but settlement config incomplete; missing: " + ", ".join(missing)
        )


# --------------------------- replay protection ----------------------------


class ReplayStore:
    """Single-use nonce store — a settled payment nonce can never be reused."""

    def __init__(self) -> None:
        self._seen: set[str] = set()
        self._lock = threading.Lock()

    def check(self, nonce: str) -> None:
        with self._lock:
            if nonce in self._seen:
                raise PaymentError("PAYMENT_REPLAYED", "payment nonce has already been used")

    def consume(self, nonce: str) -> None:
        with self._lock:
            self._seen.add(nonce)


# ------------------------------ challenge ---------------------------------


def build_challenge(config: PaymentConfig, service: str, resource: str, request_hash: str,
                    description: str) -> dict[str, Any]:
    price = config.price_for(service)
    accepts = [
        {
            "scheme": config.scheme,
            "network": config.network,
            "maxAmountRequired": price,
            "resource": resource,
            "description": description,
            "mimeType": "application/json",
            "payTo": config.recipient,
            "asset": config.asset,
            "maxTimeoutSeconds": config.max_timeout_seconds,
            "extra": {
                "name": config.asset_name,
                "decimals": config.asset_decimals,
                "service": service,
                "requestHash": request_hash,
            },
        }
    ]
    return {
        "x402Version": X402_VERSION,
        "error": PAYMENT_REQUIRED_ERROR,
        "accepts": accepts,
    }


def encode_payment_header(payload: dict[str, Any]) -> str:
    """Base64url-encode an X-PAYMENT payload (client-side helper / docs use)."""
    return base64.b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8")).decode("ascii")


def decode_payment_header(raw: str) -> dict[str, Any]:
    try:
        decoded = base64.b64decode(raw, validate=True)
        data = json.loads(decoded)
    except (binascii.Error, ValueError) as exc:
        raise PaymentError("PAYMENT_INVALID", "X-PAYMENT header is not valid base64 JSON") from exc
    if not isinstance(data, dict):
        raise PaymentError("PAYMENT_INVALID", "X-PAYMENT payload must be an object")
    return data


# ------------------------------ verify ------------------------------------


def _require(cond: bool, code: str, message: str) -> None:
    if not cond:
        raise PaymentError(code, message)


def verify_payment(
    *,
    config: PaymentConfig,
    verifier: PaymentVerifier,
    replay_store: ReplayStore,
    service: str,
    resource: str,
    request_hash: str,
    x_payment: str,
    now: float | None = None,
) -> VerificationResult:
    """Structural + binding checks, then delegated settlement. Returns a
    VerificationResult on success; raises PaymentError otherwise."""
    now = time.time() if now is None else now
    payment = decode_payment_header(x_payment)
    inner = payment.get("payload")
    _require(isinstance(inner, dict), "PAYMENT_INVALID", "payment payload is missing")

    _require(int(payment.get("x402Version", 0)) == X402_VERSION, "PAYMENT_INVALID", "unsupported x402 version")
    _require(payment.get("scheme") == config.scheme, "PAYMENT_INVALID", "unexpected payment scheme")
    _require(payment.get("network") == config.network, "PAYMENT_INVALID", "wrong network (chain) for payment")

    _require(str(inner.get("payTo")) == str(config.recipient), "PAYMENT_INVALID", "wrong payment recipient")
    _require(str(inner.get("asset")) == str(config.asset), "PAYMENT_INVALID", "wrong payment asset (token)")

    required_amount = config.price_for(service)
    _require(required_amount is not None, "PAYMENT_INVALID", "no price configured for this service")
    try:
        _require(int(inner.get("amount", -1)) >= int(required_amount), "PAYMENT_INVALID",
                 "insufficient payment amount")
    except (TypeError, ValueError) as exc:
        raise PaymentError("PAYMENT_INVALID", "payment amount is not an integer atomic value") from exc

    valid_before = inner.get("validBefore")
    _require(isinstance(valid_before, (int, float)) and valid_before > now,
             "PAYMENT_INVALID", "payment authorization has expired")

    # Per-request binding: the payment must have been minted for THIS request.
    _require(str(inner.get("requestHash")) == request_hash, "PAYMENT_INVALID",
             "payment is not bound to this request")
    _require(str(inner.get("service")) == service, "PAYMENT_INVALID", "payment is bound to a different service")

    nonce = inner.get("nonce")
    _require(isinstance(nonce, str) and nonce, "PAYMENT_INVALID", "payment nonce is missing")
    replay_store.check(nonce)  # raises PAYMENT_REPLAYED if seen

    # Never accept a private key in the payload.
    _require(not any(k in inner for k in ("privateKey", "private_key", "secret", "mnemonic")),
             "PAYMENT_INVALID", "payment payload must not contain secret key material")

    result = verifier.verify(config, service, resource, request_hash, payment)
    if result.success:
        replay_store.consume(nonce)
    return result
