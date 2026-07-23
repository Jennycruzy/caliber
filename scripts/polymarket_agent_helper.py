#!/usr/bin/env python3
"""Local caller helper for TrueOdds Polymarket execution.

This runs on the caller agent's machine, never on the ASP server. It may load
the caller's private key locally, prepare the caller's Polymarket deposit
wallet/pUSD balance, sign a POLY_1271 order, and print the JSON body to send to
TrueOdds `POST /v1/executions/{intent_id}/submit-signed`.
"""
from __future__ import annotations

import argparse
import base64
import importlib.util
import json
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from urllib import request as urllib_request


def _load_spike_module():
    path = Path(__file__).with_name("g0_spike.py")
    spec = importlib.util.spec_from_file_location("g0_spike_helper", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load g0_spike.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _prepared_response(path: str) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data


def _prepared_intent(data: dict) -> dict:
    return data.get("intent") or data


def _required_units(intent: dict) -> int:
    return int(Decimal(intent["price"]) * Decimal(intent["quantity"]) * Decimal(10 ** 6))


def _bridge_units(g0, intent: dict) -> int:
    """Amount to send through the bridge, floored at the bridge minimum.

    Sizing from the order notional alone underfunds any order below the floor,
    and the bridge neither credits pUSD nor reports an error when that happens.
    Every bridge call sizes through here so no path can skip the floor.
    """
    return max(_required_units(intent), g0.POLYMARKET_BRIDGE_MIN_UNITS)


def _agentic_wallet_owner() -> str:
    """Read the caller's EVM address from the logged-in Agentic Wallet session.

    No private key is involved: the address is session state held by OnchainOS.
    """
    result = subprocess.run(
        ["onchainos", "wallet", "addresses", "--chain", "xlayer"],
        check=True, capture_output=True, text=True,
    )
    payload = json.loads(result.stdout)
    if not payload.get("ok"):
        raise SystemExit(f"onchainos wallet addresses failed: {payload}")
    entries = (payload.get("data") or {}).get("xlayer") or []
    if not entries:
        raise SystemExit(
            "no X Layer address in the Agentic Wallet session; run `onchainos wallet login` first"
        )
    return entries[0]["address"]


def _derive_deposit_wallet_for_owner(g0, owner: str) -> str:
    from eth_utils import to_checksum_address
    from py_builder_relayer_client.builder.derive import (
        derive_beacon_deposit_wallet,
        derive_uups_deposit_wallet,
    )
    from py_builder_relayer_client.config import get_contract_config

    cfg = get_contract_config(137)
    owner = to_checksum_address(owner)
    uups = derive_uups_deposit_wallet(owner, cfg.deposit_wallet_factory, cfg.deposit_wallet_implementation)
    try:
        beacon = g0._rpc("eth_call", [{"to": cfg.deposit_wallet_factory, "data": "0x49493a4d"}, "latest"])
    except SystemExit:
        return uups
    if not isinstance(beacon, str) or len(beacon) < 66:
        return uups
    beacon_address = "0x" + beacon[-40:]
    if beacon_address.lower() == "0x0000000000000000000000000000000000000000":
        return uups
    code = g0._rpc("eth_getCode", [uups, "latest"])
    if isinstance(code, str) and code not in ("0x", "0x0"):
        return uups
    return derive_beacon_deposit_wallet(owner, cfg.deposit_wallet_factory, beacon_address)


def _spender_for_token(env: dict, token_id: str) -> str:
    from py_clob_client_v2 import ClobClient
    from py_clob_client_v2.config import get_contract_config

    chain_id = int(env.get("SPIKE_CHAIN_ID", "137"))
    client = ClobClient(env.get("SPIKE_CLOB_HOST", "https://clob.polymarket.com"), chain_id)
    neg_risk = client.get_neg_risk(token_id)
    cfg = get_contract_config(chain_id)
    return cfg.neg_risk_exchange_v2 if neg_risk else cfg.exchange_v2


def _submit_url(prepared: dict, asp_url: str | None) -> str:
    packaged = ((prepared.get("client_execution") or {}).get("submit_signed") or {}).get("url")
    if packaged:
        return packaged
    intent = _prepared_intent(prepared)
    if not asp_url:
        raise SystemExit("--asp-url is required when the prepared response does not include client_execution.submit_signed.url")
    return f"{asp_url.rstrip('/')}/v1/executions/{intent['intent_id']}/submit-signed"


def _post_submit_signed(url: str, payload: dict) -> dict:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    req = urllib_request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib_request.urlopen(req, timeout=45) as response:
        return json.loads(response.read().decode("utf-8"))


def _xlayer_stable_symbol(source_asset: str, env: dict) -> str:
    if env.get("SPIKE_XLAYER_STABLE_SYMBOL"):
        return env["SPIKE_XLAYER_STABLE_SYMBOL"].lower()
    if source_asset == "xlayer-usdt0":
        return "usdt0"
    return "usdt"


def _xlayer_usdt_to_polymarket_deposit(g0, env: dict, intent: dict, source_asset: str) -> None:
    from eth_account import Account

    owner = Account.from_key(env["SPIKE_PRIVATE_KEY"]).address
    wallet = env["SPIKE_FUNDER_ADDRESS"]
    amount = _bridge_units(g0, intent)
    bridge_address = g0._polymarket_bridge_deposit_address(env, wallet)
    stable = _xlayer_stable_symbol(source_asset, env)
    command = [
        "onchainos", "cross-chain", "execute",
        "--from", stable,
        "--to", stable,
        "--from-chain", "xlayer",
        "--to-chain", "polygon",
        "--readable-amount", g0._units(amount),
        "--wallet", env.get("SPIKE_OKX_WALLET_ADDRESS", owner),
        "--receive-address", bridge_address.lower(),
    ]
    g0.step("0x", f"SETUP: routing X Layer {stable.upper()} to caller's Polymarket deposit address")
    print("   " + " ".join(command))
    subprocess.run(command, check=True)
    g0._wait_for_wallet_pusd(env, wallet, _required_units(intent), f"X Layer {stable.upper()} route")


def _agentic_wallet_bridge_fund(
    g0, env: dict, intent: dict, source_asset: str
) -> None:
    """Fund the caller's deposit wallet from X Layer USDT/USDT0 with no private key.

    Every transaction here is signed by the caller's own Agentic Wallet session
    through the OnchainOS CLI. Nothing in this function has, derives, or needs
    key material, so it is safe to run unattended for an ASP buyer.
    """
    wallet = env["SPIKE_FUNDER_ADDRESS"]
    owner = _agentic_wallet_owner()
    amount = _bridge_units(g0, intent)
    bridge_address = g0._polymarket_bridge_deposit_address(env, wallet)
    stable = _xlayer_stable_symbol(source_asset, env)
    command = [
        "onchainos", "cross-chain", "execute",
        "--from", stable,
        "--to", stable,
        "--from-chain", "xlayer",
        "--to-chain", "polygon",
        "--readable-amount", g0._units(amount),
        "--wallet", owner,
        "--receive-address", bridge_address.lower(),
    ]
    g0.step(
        "0x",
        f"SETUP: routing X Layer {stable.upper()} via Agentic Wallet (no private key)",
    )
    print("   " + " ".join(command))
    subprocess.run(command, check=True)
    g0._wait_for_wallet_pusd(
        env, wallet, _required_units(intent), f"X Layer {stable.upper()} route"
    )


def _funding_plan(g0, env: dict, intent: dict, prepared: dict, source_asset: str, asp_url: str | None) -> dict:
    if not env.get("SPIKE_FUNDER_ADDRESS"):
        env["SPIKE_FUNDER_ADDRESS"] = g0.derive_deposit_wallet_address(env)
    plan = {
        "intent_id": intent.get("intent_id"),
        "notional": intent.get("notional") or str(Decimal(intent["price"]) * Decimal(intent["quantity"])),
        "caller_deposit_wallet": env["SPIKE_FUNDER_ADDRESS"],
        "source_asset": source_asset,
        "submit_signed_url": _submit_url(prepared, asp_url),
        "one_flow": True,
        "custody": "source transactions, order signing, and L2 headers are created by the caller-side helper only",
    }
    if source_asset in ("xlayer-usdt", "xlayer-usdt0"):
        bridge_address = g0._polymarket_bridge_deposit_address(env, env["SPIKE_FUNDER_ADDRESS"])
        amount = _bridge_units(g0, intent)
        # State the floor and the amount actually being sent. A plan that shows
        # only the sent amount looks like an unexplained mismatch with the order
        # notional, which is exactly when a caller "corrects" it downward.
        plan["minimum_deposit"] = {
            "base_units": str(g0.POLYMARKET_BRIDGE_MIN_UNITS),
            "amount": g0._units(g0.POLYMARKET_BRIDGE_MIN_UNITS),
            "note": "bridge credits no pUSD below this and reports no error",
        }
        plan["send_amount"] = {
            "base_units": str(amount),
            "amount": g0._units(amount),
            "floored_to_minimum": amount > _required_units(intent),
        }
        stable = _xlayer_stable_symbol(source_asset, env)
        plan["route"] = {
            "type": "okx_cross_chain_then_polymarket_bridge_credit",
            "command": [
                "onchainos", "cross-chain", "execute",
                "--from", stable, "--to", stable,
                "--from-chain", "xlayer", "--to-chain", "polygon",
                "--readable-amount", g0._units(amount),
                "--wallet", env.get("SPIKE_OKX_WALLET_ADDRESS", "<caller-wallet>"),
                "--receive-address", bridge_address.lower(),
            ],
            "accepted_source_symbols": ["USDT", "USDT0"],
            "selected_source_symbol": stable.upper(),
            "then": "wait for pUSD in caller_deposit_wallet, sign POLY_1271 order, call submit-signed",
        }
    else:
        plan["route"] = {
            "type": "polygon_local_setup",
            "assets": ["pUSD", "USDC.e", "native USDC", "USDT"],
            "then": "scripts/g0_spike.py setup_deposit_wallet deploys/wraps/bridges/approves as needed",
        }
    return plan


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare a caller-signed TrueOdds submit-signed payload")
    parser.add_argument("--env-file", default=".env.spike", help="local env file containing SPIKE_PRIVATE_KEY")
    parser.add_argument("--intent-file", required=True, help="JSON prepared execution intent from the ASP")
    parser.add_argument("--setup", action="store_true", help="deploy/wrap/approve pUSD before signing")
    parser.add_argument("--execute", action="store_true",
                        help="run the full caller-side flow: fund/setup, sign, and submit-signed to the ASP")
    parser.add_argument("--asp-url", help="ASP base URL used when the prepared response does not include a submit URL")
    parser.add_argument("--wallet-backend", default="local-private-key",
                        choices=["local-private-key", "okx-agentic-wallet"],
                        help="signing/funding backend used by the caller-side helper")
    parser.add_argument("--owner-address",
                        help="caller EVM owner address; used by okx-agentic-wallet planning without a private key")
    parser.add_argument("--deposit-wallet-address",
                        help="caller Polymarket POLY_1271 deposit wallet; avoids private-key derivation in planning mode")
    parser.add_argument("--source-asset", default="auto",
                        choices=["auto", "polygon", "polygon-pusd", "polygon-usdce", "polygon-usdc", "polygon-usdt", "xlayer-usdt", "xlayer-usdt0"],
                        help="caller funding source; X Layer USDT and USDT0 both route through OKX/onchainos")
    parser.add_argument("--funding-plan", action="store_true",
                        help="print machine-readable funding/sign/submit plan instead of executing")
    args = parser.parse_args()

    # Funding and order signing are separate capabilities and are gated
    # separately. Bridging needs only the wallet session, which the Agentic
    # Wallet already provides, so it runs unattended for an ASP buyer. Order
    # signing needs a POLY_1271 adapter that is not built yet, so only that step
    # refuses. Gating both behind one flag made buyers do funding by hand for a
    # reason that never applied to funding.
    g0 = _load_spike_module()
    prepared = _prepared_response(args.intent_file)
    intent = _prepared_intent(prepared)

    if args.wallet_backend == "okx-agentic-wallet":
        # The owner address is session state, so resolve it from the logged-in
        # wallet rather than making the caller paste it. An explicit flag still
        # wins, which keeps planning usable without a live session.
        owner = args.owner_address
        if not owner and not args.deposit_wallet_address:
            owner = _agentic_wallet_owner()
        env = {
            "SPIKE_CHAIN_ID": "137",
            "SPIKE_FUNDER_ADDRESS": (
                args.deposit_wallet_address or _derive_deposit_wallet_for_owner(g0, owner or "")
            ),
        }
        if args.funding_plan:
            print(json.dumps(_funding_plan(g0, env, intent, prepared, args.source_asset, args.asp_url),
                             separators=(",", ":")))
            return
        if args.setup or args.execute:
            if args.source_asset not in ("xlayer-usdt", "xlayer-usdt0"):
                raise SystemExit(
                    f"okx-agentic-wallet autonomous funding currently implements "
                    f"--source-asset xlayer-usdt or xlayer-usdt0, not "
                    f"{args.source_asset!r}"
                )
            _agentic_wallet_bridge_fund(g0, env, intent, args.source_asset)
        # Funding is done and the deposit wallet is credited. Signing is the only
        # step this backend cannot do yet, so it is the only step that refuses.
        raise SystemExit(
            "funding complete via Agentic Wallet. POLY_1271 order signing through "
            "the Agentic Wallet session is not implemented yet, so this run stops "
            "before signing; use --funding-plan to emit the remaining steps"
        )

    g0.ENV_PATH = Path(args.env_file)
    env = g0.load_env()
    env["SPIKE_SIGNATURE_TYPE"] = "3"
    env["SPIKE_TOKEN_ID"] = intent["token_id"]
    env["SPIKE_SIDE"] = "BUY"
    env["SPIKE_PRICE"] = intent["price"]
    env["SPIKE_SIZE"] = intent["quantity"]
    if not env.get("SPIKE_FUNDER_ADDRESS"):
        env["SPIKE_FUNDER_ADDRESS"] = g0.derive_deposit_wallet_address(env)

    if args.funding_plan:
        print(json.dumps(_funding_plan(g0, env, intent, prepared, args.source_asset, args.asp_url), separators=(",", ":")))
        return

    if args.execute and args.source_asset in ("xlayer-usdt", "xlayer-usdt0"):
        _xlayer_usdt_to_polymarket_deposit(g0, env, intent, args.source_asset)

    if args.setup or args.execute:
        spender = _spender_for_token(env, intent["token_id"])
        g0.setup_deposit_wallet(env, _required_units(intent), spender)

    _, body_bytes, headers = g0.caller_stage_poly_1271(env)
    submit_body = {
        "body_base64": base64.b64encode(body_bytes).decode("ascii"),
        "headers": headers,
    }
    if args.execute:
        print(json.dumps(_post_submit_signed(_submit_url(prepared, args.asp_url), submit_body), separators=(",", ":")))
    else:
        print(json.dumps(submit_body, separators=(",", ":")))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
