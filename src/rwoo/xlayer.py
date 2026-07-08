"""X Layer anchoring helpers.

This module verifies the live RPC path and reports whether the OKX Agentic
Wallet anchoring path has been verified and approved. It deliberately does not
fall back to an unverified raw-key transaction or fake a mainnet anchor.
"""
from __future__ import annotations

import os
from typing import Any

import httpx

XLAYER_CHAIN_ID = 196
OKX_XLAYER_RPC = "https://xlayerrpc.okx.com"
THIRDWEB_XLAYER_RPC = "https://196.rpc.thirdweb.com"
EXPLORER_TX_BASE = "https://www.oklink.com/xlayer/tx/"

# keccak256("UserOperationEvent(bytes32,address,address,uint256,bool,uint256,uint256)")
# — the ERC-4337 EntryPoint event. This Agentic Wallet is an ERC-4337 smart
# account: a bundler's outer transaction can report receipt status "0x1"
# (success) even when the inner UserOperation it carried reverted — the
# EntryPoint's handleOps() does not bubble a single op's revert up to the
# outer call, it just emits this event with success=false and moves on. An
# anchor is NOT proven by outer receipt status alone; this exact miss caused
# a false "anchored: true" earlier in this project's history (see
# docs/VERIFICATION_LEDGER.md) and is why this decode exists.
USER_OPERATION_EVENT_TOPIC = "0x49628fd1471006c1482da88028e9ce4dbb080b815c9b0344d39e5a8e6ec1419f"


def _decode_user_operation_event(log: dict[str, Any], sender_address: str) -> dict[str, Any] | None:
    """Returns the decoded {user_op_hash, sender, paymaster, nonce, success,
    actual_gas_cost, actual_gas_used} for the log matching our sender, or
    None if this log isn't a UserOperationEvent for that sender."""
    topics = log.get("topics") or []
    if not topics or topics[0].lower() != USER_OPERATION_EVENT_TOPIC:
        return None
    if len(topics) < 3:
        return None
    log_sender = "0x" + topics[2][-40:]
    if log_sender.lower() != sender_address.lower():
        return None
    data_hex = (log.get("data") or "0x")[2:]
    words = [data_hex[i : i + 64] for i in range(0, len(data_hex), 64)]
    if len(words) < 4:
        return None
    return {
        "user_op_hash": topics[1],
        "sender": log_sender,
        "paymaster": "0x" + topics[3][-40:] if len(topics) > 3 else None,
        "nonce": int(words[0], 16),
        "success": int(words[1], 16) == 1,
        "actual_gas_cost": int(words[2], 16),
        "actual_gas_used": int(words[3], 16),
    }


def _hex_to_int(value: str | None) -> int | None:
    if not value:
        return None
    return int(value, 16)


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
    raw_private_key_present = bool(os.environ.get("XLAYER_PRIVATE_KEY"))
    return {
        "ready": False,
        "primary_path": "OKX Agentic Wallet",
        "missing": [
            "verified OKX Agentic Wallet transaction-signing flow for anchoring a receipt commitment on X Layer"
        ],
        "fallback_private_key_present": raw_private_key_present,
        "signing_note": (
            "The build spec makes OKX Agentic Wallet the primary path. A raw funded key is not treated as "
            "completion unless the operator explicitly approves that fallback and the signing implementation "
            "is separately verified."
        ),
    }


def verify_anchor_transaction(
    *,
    tx_hash: str,
    commitment_hash: str,
    wallet_address: str,
    rpc_url: str = OKX_XLAYER_RPC,
) -> dict[str, Any]:
    normalized_commitment = commitment_hash.removeprefix("0x").lower()
    normalized_wallet = wallet_address.removeprefix("0x").lower()
    tx_data = rpc_call(rpc_url, "eth_getTransactionByHash", [tx_hash])
    receipt_data = rpc_call(rpc_url, "eth_getTransactionReceipt", [tx_hash])
    tx = tx_data.get("result")
    receipt = receipt_data.get("result")
    if not tx or not receipt:
        return {
            "anchored": False,
            "commitment_hash": commitment_hash,
            "transaction_hash": tx_hash,
            "reason": "transaction or receipt not found on X Layer RPC",
        }
    tx_input = tx.get("input", "").lower()
    receipt_status = receipt.get("status")
    chain_id = _hex_to_int(tx.get("chainId"))
    block_number = _hex_to_int(receipt.get("blockNumber"))
    gas_used = _hex_to_int(receipt.get("gasUsed"))
    effective_gas_price = _hex_to_int(receipt.get("effectiveGasPrice"))
    fee_wei = gas_used * effective_gas_price if gas_used is not None and effective_gas_price is not None else None

    user_op = None
    for log in receipt.get("logs") or []:
        decoded = _decode_user_operation_event(log, wallet_address)
        if decoded is not None:
            user_op = decoded
            break

    checks = {
        "chain_id_is_196": chain_id == XLAYER_CHAIN_ID,
        "receipt_status_success": receipt_status == "0x1",
        "commitment_hash_in_transaction_input": normalized_commitment in tx_input,
        "wallet_address_in_transaction_input": normalized_wallet in tx_input,
        # This is the check that actually matters for an ERC-4337 account —
        # not just "did the bundler's outer transaction succeed" but "did our
        # specific UserOperation, inside it, actually execute successfully."
        "user_operation_event_found": user_op is not None,
        "user_operation_success": bool(user_op and user_op["success"]),
    }
    anchored = all(checks.values())
    return {
        "anchored": anchored,
        "commitment_hash": commitment_hash,
        "transaction_hash": tx_hash,
        "explorer_url": EXPLORER_TX_BASE + tx_hash,
        "rpc_url": rpc_url,
        "chain_id": chain_id,
        "block_number": block_number,
        "from": tx.get("from"),
        "to": tx.get("to"),
        "input_contains_commitment": checks["commitment_hash_in_transaction_input"],
        "input_contains_wallet_address": checks["wallet_address_in_transaction_input"],
        "receipt_status": receipt_status,
        "user_operation_event": user_op,
        "gas_used": gas_used,
        "effective_gas_price_wei": effective_gas_price,
        "fee_wei": fee_wei,
        "checks": checks,
        "reason": (
            "verified X Layer transaction: UserOperation executed successfully and contains the commitment hash"
            if anchored
            else "anchor verification checks failed"
        ),
    }


def anchor_commitment(
    commitment_hash: str,
    *,
    tx_hash: str | None = None,
    wallet_address: str | None = None,
) -> dict[str, Any]:
    if tx_hash and wallet_address:
        return verify_anchor_transaction(
            tx_hash=tx_hash,
            commitment_hash=commitment_hash,
            wallet_address=wallet_address,
        )
    prereq = anchoring_prerequisites()
    return {
        "anchored": False,
        "commitment_hash": commitment_hash,
        "reason": "missing verified OKX Agentic Wallet anchoring transaction metadata",
        "prerequisites": prereq,
    }
