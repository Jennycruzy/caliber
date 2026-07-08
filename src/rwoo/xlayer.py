"""X Layer anchoring helpers.

This module verifies the live RPC path and reports whether the environment has
the prerequisites for a real mainnet anchor. It deliberately does not fake a
transaction when a signer is missing.
"""
from __future__ import annotations

import os
from typing import Any

import httpx

XLAYER_CHAIN_ID = 196
OKX_XLAYER_RPC = "https://xlayerrpc.okx.com"
THIRDWEB_XLAYER_RPC = "https://196.rpc.thirdweb.com"
EXPLORER_TX_BASE = "https://www.oklink.com/xlayer/tx/"


def rpc_call(rpc_url: str, method: str, params: list[Any] | None = None, timeout: float = 20) -> dict[str, Any]:
    resp = httpx.post(
        rpc_url,
        json={"jsonrpc": "2.0", "method": method, "params": params or [], "id": 1},
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"RPC error from {rpc_url}: {data['error']}")
    return data


def verify_rpc_endpoints() -> list[dict[str, Any]]:
    results = []
    for rpc_url in (OKX_XLAYER_RPC, THIRDWEB_XLAYER_RPC):
        data = rpc_call(rpc_url, "eth_chainId")
        chain_id = int(data["result"], 16)
        results.append(
            {
                "rpc_url": rpc_url,
                "raw_chain_id": data["result"],
                "chain_id": chain_id,
                "ok": chain_id == XLAYER_CHAIN_ID,
            }
        )
    return results


def anchoring_prerequisites() -> dict[str, Any]:
    private_key_present = bool(os.environ.get("XLAYER_PRIVATE_KEY"))
    return {
        "ready": private_key_present,
        "missing": [] if private_key_present else ["XLAYER_PRIVATE_KEY for a funded X Layer account"],
        "signing_note": (
            "No Python EVM signing dependency is installed in this workspace; a real anchor needs "
            "either an approved OKX Agentic Wallet flow or a vetted signing dependency plus a funded key."
        ),
    }


def anchor_commitment(commitment_hash: str) -> dict[str, Any]:
    prereq = anchoring_prerequisites()
    if not prereq["ready"]:
        return {
            "anchored": False,
            "commitment_hash": commitment_hash,
            "reason": "missing X Layer mainnet signer prerequisite",
            "prerequisites": prereq,
        }
    return {
        "anchored": False,
        "commitment_hash": commitment_hash,
        "reason": (
            "XLAYER_PRIVATE_KEY is present, but no vetted EVM signing implementation is installed. "
            "Refusing to hand-roll transaction signing for mainnet funds."
        ),
        "prerequisites": prereq,
    }
