#!/usr/bin/env python3
"""G0 spike — prove Variant A: a third party can relay a caller-signed order.

WHAT THIS PROVES (or disproves)
-------------------------------
The non-custodial design in ``docs/EXECUTION_BUILD_PLAN.md`` rests on one
unverified claim: that TrueOdds can accept an order a caller signed *and*
authenticated locally, forward it **byte for byte**, and have Polymarket accept
it — while TrueOdds holds no secret of any kind.

Polymarket auth has two levels. L1 (the private key) signs the order struct;
L2 (apiKey/secret/passphrase, HMAC-SHA256) authenticates the HTTP request. The
adapter never needs L1. But L2 headers are still required on ``POST /order``,
and they are computed over the request body. That is the crux: if the relay
re-serializes the body at any point, the HMAC breaks and Variant A is dead.

STRUCTURE — read this before running
------------------------------------
The script splits into two roles with a hard boundary:

    caller_stage()   holds the key, signs, builds L2 headers, emits opaque bytes
    relay_stage()    receives ONLY (path, body_bytes, headers) — no key, no
                     secret, no ability to re-sign. This is TrueOdds.

``relay_stage`` is deliberately written to take no credential argument. If a
future edit needs to pass one in, Variant A has failed and the plan must fall
back to Variant B. That signature is the experiment.

USAGE
-----
    cp .env.spike.example .env.spike && chmod 600 .env.spike
    # fill in .env.spike, then:
    python scripts/g0_spike.py --pick-market      # find a market, no key needed
    python scripts/g0_spike.py --dry-run          # everything except the POST
    python scripts/g0_spike.py --live             # actually rests an order

``--dry-run`` is the default. ``--live`` spends real money; keep it tiny.

SECRETS
-------
Nothing here prints a secret. Values loaded from .env.spike are redacted in all
output. Run it yourself — the key does not need to pass through anyone else.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ENV_PATH = REPO / ".env.spike"

REQUIRED = ("SPIKE_PRIVATE_KEY", "SPIKE_FUNDER_ADDRESS", "SPIKE_TOKEN_ID")
SECRET_KEYS = ("SPIKE_PRIVATE_KEY",)


# ---------------------------------------------------------------- utilities


def redact(key: str, value: str) -> str:
    """Never let key material reach stdout, a log, or a screen share."""
    if key in SECRET_KEYS or "KEY" in key or "SECRET" in key or "PASSPHRASE" in key:
        return f"<redacted:{len(value)} chars>"
    return value


def load_env() -> dict[str, str]:
    if not ENV_PATH.exists():
        die(f"{ENV_PATH.name} not found. Copy .env.spike.example to .env.spike and fill it in.")

    mode = stat.S_IMODE(ENV_PATH.stat().st_mode)
    if mode & 0o077:
        die(f"{ENV_PATH.name} is mode {mode:o} — readable by others. Run: chmod 600 {ENV_PATH}")

    env: dict[str, str] = {}
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip()

    missing = [k for k in REQUIRED if not env.get(k)]
    if missing:
        die(f"{ENV_PATH.name} is missing: {', '.join(missing)}")
    return env


def die(message: str) -> None:
    print(f"\n  FAIL  {message}\n", file=sys.stderr)
    raise SystemExit(1)


def step(number: str, title: str) -> None:
    print(f"\n[{number}] {title}")


def ok(message: str) -> None:
    print(f"   ok   {message}")


def warn(message: str) -> None:
    print(f"   !!   {message}")


def require_sdk():
    """py-clob-client owns the exact auth conventions. Do not reimplement them.

    The L2 HMAC is computed over a string the *server* reconstructs its own way.
    Hand-rolling that serialization is precisely the class of subtle mismatch
    this spike exists to avoid, so the credential and order-signing steps go
    through the official SDK and only the relay boundary is ours.
    """
    try:
        import py_clob_client  # noqa: F401
    except ImportError:
        die(
            "py-clob-client is not installed. In a scratch venv:\n"
            "        python -m venv .venv-spike && . .venv-spike/bin/activate\n"
            "        pip install py-clob-client\n"
            "      Pin the exact version you use into docs/EXECUTION_BUILD_PLAN.md (gate A)."
        )


# ---------------------------------------------------------------- discovery


def pick_market(host: str) -> None:
    """Find a liquid market and print ready-to-paste .env.spike lines."""
    import httpx

    with httpx.Client(timeout=30, headers={"User-Agent": "curl/8.5.0"}) as client:
        response = client.get(f"{host}/sampling-markets")
        response.raise_for_status()
        markets = response.json().get("data") or []

    live = [
        m for m in markets
        if m.get("active") and not m.get("closed")
        and m.get("accepting_orders") and not m.get("neg_risk")
    ]
    if not live:
        die("no active, order-accepting, non-neg-risk market found")

    print(f"\nFound {len(live)} candidate markets. First few:\n")
    for market in live[:5]:
        yes = next((t for t in market["tokens"] if t["outcome"].upper() == "YES"), None)
        if not yes:
            continue
        print(f"  {market['question'][:70]}")
        print(f"    tick={market.get('minimum_tick_size')}  min_size={market.get('minimum_order_size')}")
        print(f"    SPIKE_CONDITION_ID={market['condition_id']}")
        print(f"    SPIKE_TOKEN_ID={yes['token_id']}")
        print()

    print("Pick one, paste its two lines into .env.spike, and choose a price far")
    print("from the touch so the order RESTS rather than fills.\n")


# ---------------------------------------------------------------- the roles


def caller_stage(env: dict[str, str]) -> tuple[str, bytes, dict[str, str]]:
    """The CALLER's agent. Holds the key. Returns only what a relay may see.

    Everything secret stays inside this function. The return value is the exact
    payload TrueOdds would receive over the wire: a path, opaque bytes, and
    headers the caller already computed.
    """
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import ApiCreds, OrderArgs
    from py_clob_client.order_builder.constants import BUY, SELL

    chain_id = int(env.get("SPIKE_CHAIN_ID", "137"))
    host = env.get("SPIKE_CLOB_HOST", "https://clob.polymarket.com")
    sig_type = int(env.get("SPIKE_SIGNATURE_TYPE", "0"))

    step("1", "CALLER: initialise client with the throwaway key (L1)")
    kwargs = {"key": env["SPIKE_PRIVATE_KEY"], "chain_id": chain_id}
    if sig_type != 0:
        kwargs["signature_type"] = sig_type
        kwargs["funder"] = env["SPIKE_FUNDER_ADDRESS"]
    client = ClobClient(host, **kwargs)
    ok(f"signer address {client.get_address()}")
    if client.get_address().lower() != env["SPIKE_FUNDER_ADDRESS"].lower() and sig_type == 0:
        warn("SPIKE_FUNDER_ADDRESS does not match the derived address (fine only if sig_type != 0)")

    step("2", "CALLER: derive L2 credentials from the key (never leaves this box)")
    creds = client.create_or_derive_api_creds()
    client.set_api_creds(creds)
    ok("L2 creds derived: " + ", ".join(
        f"{name}={redact(name.upper(), str(getattr(creds, name)))}"
        for name in ("api_key", "api_secret", "api_passphrase")
        if hasattr(creds, name)
    ))

    step("3", "CALLER: build and sign the order struct (L1 signature)")
    side = BUY if env.get("SPIKE_SIDE", "BUY").upper() == "BUY" else SELL
    order = client.create_order(OrderArgs(
        token_id=env["SPIKE_TOKEN_ID"],
        price=float(env.get("SPIKE_PRICE", "0.02")),
        size=float(env.get("SPIKE_SIZE", "5")),
        side=side,
    ))
    ok("order signed locally; the private key never leaves this function")

    step("4", "CALLER: serialise ONCE and compute L2 headers over those bytes")
    # This is the crux of Variant A. The body is serialised exactly once. The
    # same object is used to build the HMAC and is then frozen to bytes. If the
    # relay ever re-serialises, the HMAC will not verify server-side.
    from py_clob_client.headers.headers import create_level_2_headers
    from py_clob_client.clob_types import RequestArgs

    body = order.dict() if hasattr(order, "dict") else json.loads(json.dumps(order, default=str))
    payload = {"order": body, "owner": creds.api_key, "orderType": "GTC"}

    request_args = RequestArgs(method="POST", request_path="/order", body=payload)
    headers = create_level_2_headers(client.signer, creds, request_args)

    body_bytes = json.dumps(payload).encode()
    ok(f"body frozen: {len(body_bytes)} bytes, sha256={hashlib.sha256(body_bytes).hexdigest()[:16]}…")
    ok(f"headers computed by the CALLER: {sorted(headers)}")

    return "/order", body_bytes, dict(headers)


def relay_stage(host: str, path: str, body_bytes: bytes, headers: dict[str, str],
                *, live: bool) -> dict | None:
    """TrueOdds. Receives opaque bytes and pre-computed headers. Holds nothing.

    NOTE THE SIGNATURE. There is no key parameter, no credential parameter, and
    no way to obtain one. This function cannot sign, cannot re-authenticate, and
    cannot create an order. It can only forward what it was handed — which is
    exactly the authority Variant A claims TrueOdds needs.
    """
    import httpx

    step("5", "RELAY: verify integrity without decoding intent")
    digest_in = hashlib.sha256(body_bytes).hexdigest()
    ok(f"received {len(body_bytes)} opaque bytes, sha256={digest_in[:16]}…")

    # A relay may inspect for its own risk checks, but must forward the ORIGINAL
    # bytes. Parsing to a dict and re-dumping is the failure mode being tested.
    try:
        preview = json.loads(body_bytes)
        ok(f"parsed for inspection only: keys={sorted(preview)}")
    except json.JSONDecodeError:
        die("relay received a body it cannot parse")

    step("6", "RELAY: forward byte-identical to the venue")
    if hashlib.sha256(body_bytes).hexdigest() != digest_in:
        die("body mutated inside the relay — Variant A violated")
    ok("body unchanged after inspection")

    if not live:
        warn("--dry-run: not posting. Re-run with --live to complete the proof.")
        print("\n   Would POST:")
        print(f"     {host}{path}")
        print(f"     headers: {sorted(headers)}")
        print(f"     body:    {len(body_bytes)} bytes (unmodified)")
        return None

    with httpx.Client(timeout=30) as client:
        # content=body_bytes — NOT json=payload. Passing a dict here would let
        # httpx re-serialise and silently invalidate the caller's HMAC.
        response = client.post(
            f"{host}{path}",
            content=body_bytes,
            headers={**headers, "Content-Type": "application/json"},
        )

    step("7", "RELAY: venue response")
    print(f"   HTTP {response.status_code}")
    try:
        result = response.json()
    except ValueError:
        print(f"   body: {response.text[:400]}")
        die("venue returned a non-JSON response")

    print("   " + json.dumps(result, indent=2)[:800].replace("\n", "\n   "))
    return result


# ---------------------------------------------------------------- entrypoint


def main() -> None:
    parser = argparse.ArgumentParser(description="G0 spike: prove non-custodial relay")
    parser.add_argument("--pick-market", action="store_true",
                        help="list candidate markets; needs no key")
    parser.add_argument("--live", action="store_true",
                        help="actually POST the order (spends real money)")
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="do everything except the POST (default)")
    args = parser.parse_args()

    host = os.environ.get("SPIKE_CLOB_HOST", "https://clob.polymarket.com")

    if args.pick_market:
        pick_market(host)
        return

    print("=" * 72)
    print("G0 SPIKE — Variant A: caller signs and authenticates, relay forwards")
    print("=" * 72)

    require_sdk()
    env = load_env()
    host = env.get("SPIKE_CLOB_HOST", host)

    if args.live:
        warn("LIVE MODE — this will rest a real order with real funds.")
        if input("   type 'yes' to continue: ").strip().lower() != "yes":
            die("aborted by operator")

    path, body_bytes, headers = caller_stage(env)

    # The boundary. Everything above held the key; nothing below can reach it.
    result = relay_stage(host, path, body_bytes, headers, live=args.live)

    print("\n" + "=" * 72)
    if result is None:
        print("DRY RUN COMPLETE — signing and header construction verified.")
        print("G0 is NOT yet proven. Re-run with --live to complete it.")
    elif result.get("success") or result.get("orderID") or result.get("orderId"):
        print("G0 PASS — the venue accepted an order relayed by a party holding")
        print("no key and no credential. Variant A is proven. Record it in")
        print("docs/EXECUTION_BUILD_PLAN.md and proceed to Phase 3.")
        print("\nNow: cancel the resting order and drain the throwaway wallet.")
    else:
        print("G0 INCONCLUSIVE — the venue rejected the relayed order.")
        print("Capture the exact error above. If it indicates an auth/HMAC")
        print("mismatch, the serialisation convention differs from this script's")
        print("and must be taken from the SDK verbatim. Only after ruling that")
        print("out does Variant A fall back to Variant B.")
    print("=" * 72)


if __name__ == "__main__":
    main()
