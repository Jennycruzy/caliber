#!/usr/bin/env python3
"""Buyer-side ASP execution client: reach pUSD and trade with the buyer's own signer.

Ties the pieces together:
  - a `Signer` the buyer chooses (raw local key, or a headless provider),
  - `buyer_funding.plan_pusd_funding` to pick the route from whatever stable the
    EOA holds, and
  - `ensure_pusd`, which walks each planned step through the chosen signer.

TrueOdds never sees the key: signing and broadcasting happen here, in the buyer's
own process. The self-contained on-chain legs (ERC-20 approve, USDC.e -> pUSD wrap)
are wired; the external legs (MESON bridge, DEX swap) are *injected* handlers,
because they need live quotes/routers the buyer supplies and that TrueOdds must
not hardcode.

Everything is dependency-injected (signer, rpc, handlers), so the orchestration is
unit-testable without a live key, RPC, or venue.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import stat
import subprocess
import sys
import time
import urllib.request
import uuid
from abc import ABC, abstractmethod
from decimal import Decimal, InvalidOperation
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import buyer_funding  # noqa: E402  (sibling module, path inserted above)

# ---------------------------------------------------------------- constants
SEL_APPROVE = "0x095ea7b3"       # approve(address,uint256)
SEL_TRANSFER = "0xa9059cbb"      # transfer(address,uint256)
SEL_BALANCE_OF = "0x70a08231"    # balanceOf(address)
SEL_ALLOWANCE = "0xdd62ed3e"     # allowance(address,address)
SEL_WRAP = "0x62355638"          # wrap(address,address,uint256) on the on-ramp

COLLATERAL_ONRAMP = "0x93070a847efEf7F70739046A929D47a521F5B8ee"
USDCE = buyer_funding.SOURCE_TOKENS["usdce"]["address"]
PUSD = buyer_funding.SOURCE_TOKENS["pusd"]["address"]

_MAX_UINT256 = (1 << 256) - 1


class ExecutionError(Exception):
    """A funding step could not be executed."""


def _addr(value: str) -> str:
    return value.lower().removeprefix("0x").rjust(64, "0")


def _uint(value: int) -> str:
    if value < 0 or value > _MAX_UINT256:
        raise ValueError(f"uint256 out of range: {value}")
    return format(value, "x").rjust(64, "0")


def _env_file(path: str | Path) -> dict[str, str]:
    """Read a local mode-600 KEY=VALUE file without evaluating shell syntax."""
    path = Path(path)
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise ExecutionError(f"{path} must not be accessible by group or other users")
    values = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values


def load_buyer_config(path: str | Path) -> dict[str, str]:
    """Load buyer settings, resolving the private key by reference.

    The buyer config contains only the path and variable name of an existing
    secret. The private key is returned in memory but is never copied into the
    dedicated config file.
    """
    config = _env_file(path)
    secret_path = config.get("BUYER_SECRET_ENV_FILE")
    secret_name = config.get("BUYER_PRIVATE_KEY_NAME")
    if not secret_path or not secret_name:
        raise ExecutionError(
            "buyer config requires BUYER_SECRET_ENV_FILE and BUYER_PRIVATE_KEY_NAME"
        )
    resolved = Path(secret_path)
    if not resolved.is_absolute():
        resolved = Path(path).resolve().parent / resolved
    secret = _env_file(resolved).get(secret_name)
    if not secret:
        raise ExecutionError("referenced buyer private key is missing")
    return {**config, "BUYER_PRIVATE_KEY": secret}


# ---------------------------------------------------------------- signer
class Signer(ABC):
    """What the client needs from a wallet. Both backends satisfy this."""

    @abstractmethod
    def address(self) -> str: ...

    @abstractmethod
    def sign_order(self, order_eip712: dict) -> str:
        """Sign a Polymarket order (EIP-712). Returns 0x-hex."""

    @abstractmethod
    def sign_and_send(self, tx: dict) -> str:
        """Broadcast an on-chain tx ({to, data, value?}). Returns the tx hash."""


class LocalKeySigner(Signer):
    """Option A — a raw EOA private key held in the buyer's own process."""

    def __init__(self, private_key: str, rpc, chain_id: int = 137):
        from eth_account import Account

        self._account = Account.from_key(private_key)
        self._rpc = rpc
        self._chain_id = chain_id

    def address(self) -> str:
        return self._account.address

    def sign_order(self, order_eip712: dict) -> str:
        from eth_account.messages import encode_typed_data

        signed = self._account.sign_message(encode_typed_data(full_message=order_eip712))
        sig = signed.signature.hex()
        return sig if sig.startswith("0x") else f"0x{sig}"

    def sign_and_send(self, tx: dict) -> str:
        addr = self._account.address
        nonce = int(self._rpc("eth_getTransactionCount", [addr, "pending"]), 16)
        gas_price = int(self._rpc("eth_gasPrice", []), 16)
        full = {
            "to": tx["to"],
            "value": tx.get("value", 0),
            "data": tx["data"],
            "nonce": nonce,
            "chainId": tx.get("chainId", self._chain_id),
            "gas": tx.get("gas", 250_000),
            "maxFeePerGas": gas_price * 2,
            "maxPriorityFeePerGas": min(gas_price, 30_000_000_000),
        }
        signed = self._account.sign_transaction(full)
        raw = signed.raw_transaction.hex()
        return self._rpc("eth_sendRawTransaction", ["0x" + raw.removeprefix("0x")])


class ProviderSigner(Signer):
    """Option B — a headless wallet provider (Turnkey / Privy / CDP).

    The buyer holds the provider API key; TrueOdds never does. Each method maps to
    the provider's sign / broadcast API. Left unimplemented on purpose — the
    provider and its auth are the buyer's choice; wire the two calls below.
    """

    def __init__(self, wallet_address: str, *, provider: str = "turnkey"):
        self._address = wallet_address
        self._provider = provider

    def address(self) -> str:
        return self._address

    def sign_order(self, order_eip712: dict) -> str:
        raise NotImplementedError(f"wire {self._provider} EIP-712 order signing")

    def sign_and_send(self, tx: dict) -> str:
        raise NotImplementedError(f"wire {self._provider} tx signing + broadcast")


# ---------------------------------------------------------------- rpc + reads
def http_rpc(url: str):
    """A minimal JSON-RPC callable: rpc(method, params) -> result."""

    def call(method: str, params: list):
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "content-type": "application/json",
                "user-agent": "TrueOdds-Buyer/1.0",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read())
        if payload.get("error"):
            raise RuntimeError(f"{method} rpc error: {payload['error']}")
        return payload["result"]

    return call


def _erc20_uint_call(rpc, token: str, selector_data: str) -> int:
    return int(rpc("eth_call", [{"to": token, "data": selector_data}, "latest"]) or "0x0", 16)


def balance_of(rpc, token: str, holder: str) -> int:
    return _erc20_uint_call(rpc, token, SEL_BALANCE_OF + _addr(holder))


def allowance(rpc, token: str, owner: str, spender: str) -> int:
    return _erc20_uint_call(rpc, token, SEL_ALLOWANCE + _addr(owner) + _addr(spender))


def ensure_bounded_approval(signer: Signer, rpc, *, token: str,
                            spender: str, required_units: int) -> str | None:
    """Approve exactly the active order requirement, never MaxUint256 or a buffer."""
    if required_units <= 0:
        raise ExecutionError("required approval must be positive")
    current = allowance(rpc, token, signer.address(), spender)
    if current >= required_units:
        return None
    tx_hash = signer.sign_and_send({
        "to": token,
        "data": SEL_APPROVE + _addr(spender) + _uint(required_units),
    })
    _wait_receipt(rpc, tx_hash)
    return tx_hash


def read_balances(rpc, address: str, *, xlayer_rpc=None) -> dict:
    """EOA balances keyed to the planner's sources. X Layer needs its own RPC."""
    out = {}
    for key, meta in buyer_funding.SOURCE_TOKENS.items():
        if meta["chain"] == "polygon":
            out[key] = balance_of(rpc, meta["address"], address)
        elif meta["chain"] == "xlayer" and xlayer_rpc is not None:
            out[key] = balance_of(xlayer_rpc, meta["address"], address)
        else:
            out[key] = 0
    return out


def _wait_receipt(rpc, tx_hash: str, *, tries: int = 40, delay: float = 3.0) -> None:
    for _ in range(tries):
        receipt = rpc("eth_getTransactionReceipt", [tx_hash])
        if receipt:
            if int(receipt.get("status", "0x0"), 16) == 1:
                return
            raise ExecutionError(f"transaction reverted: {tx_hash}")
        time.sleep(delay)
    raise ExecutionError(f"transaction not confirmed: {tx_hash}")


# ---------------------------------------------------------------- handlers
def wrap_handler(signer: Signer, rpc, step: dict) -> str:
    """USDC.e -> pUSD on-ramp, minted straight to the buyer's own EOA.

    Resolves a CREDITED amount to the EOA's current USDC.e balance (so it consumes
    whatever a preceding bridge/swap actually delivered), tops up the on-ramp
    allowance if needed, then wraps.
    """
    owner = signer.address()
    amount = step["amount_units"]
    if amount == buyer_funding.CREDITED:
        amount = balance_of(rpc, USDCE, owner)
    if amount <= 0:
        raise ExecutionError("wrap step has nothing to wrap (USDC.e balance is 0)")

    if allowance(rpc, USDCE, owner, COLLATERAL_ONRAMP) < amount:
        approve_hash = signer.sign_and_send({
            "to": USDCE,
            "data": SEL_APPROVE + _addr(COLLATERAL_ONRAMP) + _uint(amount),
        })
        _wait_receipt(rpc, approve_hash)

    wrap_hash = signer.sign_and_send({
        "to": COLLATERAL_ONRAMP,
        "data": SEL_WRAP + _addr(USDCE) + _addr(owner) + _uint(amount),
    })
    _wait_receipt(rpc, wrap_hash)
    return wrap_hash


# `bridge` and `swap` are injected: they need the buyer's MESON route / DEX router,
# and each MUST block until the destination USDC.e is credited on Polygon so the
# following CREDITED wrap can consume it. Handler signature: (signer, rpc, step).
DEFAULT_HANDLERS = {"wrap": wrap_handler}


def _onchainos_json(args: list[str]) -> dict:
    result = subprocess.run(
        ["onchainos", *args],
        capture_output=True,
        text=True,
        timeout=45,
    )
    if result.returncode != 0:
        raise ExecutionError(f"routing command failed: {' '.join(args[:2])}")
    try:
        payload = json.loads(result.stdout)
    except ValueError as exc:
        raise ExecutionError("routing command returned invalid JSON") from exc
    if payload.get("ok") is not True:
        raise ExecutionError(f"routing command refused: {payload.get('error') or 'unknown error'}")
    return payload


def polygon_swap_handler(
    signer: Signer,
    rpc,
    step: dict,
    *,
    max_slippage_bps: int = 100,
    route_builder=_onchainos_json,
) -> str:
    """Swap a supported Polygon stable into USDC.e using unsigned OKX calldata.

    The router only builds the transaction. The buyer EOA grants a bounded
    allowance, signs and broadcasts both transactions locally, and verifies the
    promised minimum output from its own on-chain balance.
    """
    if not 1 <= max_slippage_bps <= 500:
        raise ExecutionError("max_slippage_bps must be between 1 and 500")
    source = buyer_funding.SOURCE_TOKENS.get(step["from_token"])
    if not source or source["chain"] != "polygon":
        raise ExecutionError("Polygon swap handler received an unsupported source")
    amount = step["amount_units"]
    if amount == buyer_funding.CREDITED:
        amount = balance_of(rpc, source["address"], signer.address())
    if not isinstance(amount, int) or amount <= 0:
        raise ExecutionError("swap amount must be a positive integer")

    before = balance_of(rpc, USDCE, signer.address())
    payload = route_builder([
        "swap", "swap",
        "--from", source["address"],
        "--to", USDCE,
        "--chain", "polygon",
        "--amount", str(amount),
        "--wallet", signer.address(),
        "--slippage", str(max_slippage_bps / 100),
    ])
    rows = payload.get("data") or []
    if len(rows) != 1 or not isinstance(rows[0].get("tx"), dict):
        raise ExecutionError("router returned no unique unsigned swap transaction")
    tx = rows[0]["tx"]
    route = rows[0].get("routerResult") or {}
    if (route.get("fromToken") or {}).get("isHoneyPot") or (route.get("toToken") or {}).get("isHoneyPot"):
        raise ExecutionError("router marked a route token as a honeypot")
    min_receive = int(tx.get("minReceiveAmount") or 0)
    if min_receive <= 0:
        raise ExecutionError("router returned no positive minimum received amount")
    router = tx.get("to")
    data = tx.get("data")
    if not isinstance(router, str) or len(router) != 42 or not isinstance(data, str):
        raise ExecutionError("router returned malformed transaction calldata")

    if allowance(rpc, source["address"], signer.address(), router) < amount:
        approval_hash = signer.sign_and_send({
            "to": source["address"],
            "data": SEL_APPROVE + _addr(router) + _uint(amount),
        })
        _wait_receipt(rpc, approval_hash)

    swap_hash = signer.sign_and_send({
        "to": router,
        "data": data,
        "value": int(tx.get("value") or 0),
        "gas": int(tx["gas"]) if tx.get("gas") else 900_000,
    })
    _wait_receipt(rpc, swap_hash)
    received = balance_of(rpc, USDCE, signer.address()) - before
    if received < min_receive:
        raise ExecutionError(
            f"swap output below promised minimum: received {received}, minimum {min_receive}"
        )
    return swap_hash


DEFAULT_HANDLERS["swap"] = polygon_swap_handler


def make_xlayer_bridge_handler(
    xlayer_signer: Signer,
    xlayer_rpc,
    polygon_rpc,
    *,
    max_slippage_bps: int = 100,
    route_builder=_onchainos_json,
    settlement_tries: int = 80,
    settlement_delay: float = 5.0,
):
    """Build an X Layer USD₮0 -> Polygon USDT handler for one buyer EOA."""
    if xlayer_signer.address().lower() == "":
        raise ExecutionError("X Layer signer has no address")

    def bridge(_signer: Signer, _rpc, step: dict) -> str:
        if _signer.address().lower() != xlayer_signer.address().lower():
            raise ExecutionError("Polygon and X Layer signers must resolve to the same EOA")
        if step["from_token"] != "xlayer_usdt0":
            raise ExecutionError("X Layer bridge handler received an unsupported source")
        amount = step["amount_units"]
        source = buyer_funding.SOURCE_TOKENS["xlayer_usdt0"]["address"]
        destination = buyer_funding.SOURCE_TOKENS["polygon_usdt"]["address"]
        before = balance_of(polygon_rpc, destination, _signer.address())
        payload = route_builder([
            "cross-chain", "swap",
            "--from", source,
            "--to", destination,
            "--from-chain", "xlayer",
            "--to-chain", "polygon",
            "--amount", str(amount),
            "--wallet", xlayer_signer.address(),
            "--receive-address", _signer.address(),
            "--slippage", str(max_slippage_bps / 10_000),
        ])
        rows = payload.get("data") or []
        if len(rows) != 1:
            raise ExecutionError("bridge router returned no unique route")
        row = rows[0]
        tx = row.get("tx") or {}
        router = tx.get("to")
        minimum = int(row.get("minimumReceived") or 0)
        if minimum <= 0 or not isinstance(router, str) or len(router) != 42:
            raise ExecutionError("bridge route has no enforceable minimum output")
        if allowance(xlayer_rpc, source, xlayer_signer.address(), router) < amount:
            approval_hash = xlayer_signer.sign_and_send({
                "to": source,
                "data": SEL_APPROVE + _addr(router) + _uint(amount),
                "chainId": 196,
            })
            _wait_receipt(xlayer_rpc, approval_hash)
        bridge_hash = xlayer_signer.sign_and_send({
            "to": router,
            "data": tx["data"],
            "value": int(tx.get("value") or 0),
            "gas": int(tx.get("gasLimit") or 250_000),
            "chainId": 196,
        })
        _wait_receipt(xlayer_rpc, bridge_hash)
        for _ in range(settlement_tries):
            credited = balance_of(polygon_rpc, destination, _signer.address()) - before
            if credited >= minimum:
                return bridge_hash
            time.sleep(settlement_delay)
        raise ExecutionError("bridge source confirmed but destination minimum was not credited")

    return bridge


# ---------------------------------------------------------------- orchestrator
def ensure_pusd(
    signer: Signer,
    rpc,
    required_units: int,
    *,
    handlers: dict | None = None,
    xlayer_rpc=None,
    margin_bps: int = 0,
) -> dict:
    """Bring the buyer's EOA to `required_units` pUSD, signing every step locally.

    Reads the EOA's balances, plans the route, and executes each step with the
    chosen signer. Injected `handlers` add/override step executors (e.g. a MESON
    `bridge` and a DEX `swap`); the built-in `wrap` needs nothing external. Returns
    a summary with the executed steps and the final pUSD balance.
    """
    active = {**DEFAULT_HANDLERS, **(handlers or {})}
    balances = read_balances(rpc, signer.address(), xlayer_rpc=xlayer_rpc)
    plan = buyer_funding.plan_pusd_funding(balances, required_units, margin_bps=margin_bps)
    if not plan:
        return {"status": "already_funded", "steps": [], "pusd_units": balances.get("pusd", 0)}

    executed = []
    for step in plan:
        handler = active.get(step["action"])
        if handler is None:
            raise ExecutionError(
                f"no handler for step '{step['action']}' — inject a "
                f"'{step['action']}' handler (MESON bridge / DEX swap) via handlers="
            )
        tx_hash = handler(signer, rpc, step)
        executed.append({"action": step["action"], "from_token": step["from_token"], "tx": tx_hash})

    final = balance_of(rpc, PUSD, signer.address())
    return {
        "status": "funded" if final >= required_units else "incomplete",
        "steps": executed,
        "pusd_units": final,
    }


# ---------------------------------------------------------------- deposit wallet
def derive_deposit_wallet(private_key: str, *, chain_id: int = 137,
                          rpc_url: str | None = None) -> str:
    """Derive the POLY_1271 deposit wallet address from a buyer's key."""
    from py_builder_relayer_client.client import RelayClient

    relayer = RelayClient(
        "https://relayer-v2.polymarket.com",
        chain_id,
        private_key,
        rpc_url=rpc_url,
    )
    return relayer.get_expected_deposit_wallet()


SEL_SET_APPROVAL_FOR_ALL = "0xa22cb465"  # setApprovalForAll(address,bool)
CONDITIONAL_TOKENS = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
EXCHANGE_V2 = "0xE111180000d2663C0091e4f400237545B87B996B"
NEG_RISK_EXCHANGE_V2 = "0xe2222d279d744050d28e00520010520000310F59"


def setup_buyer_deposit_wallet(
    signer: Signer,
    rpc,
    *,
    required_pusd_units: int,
    fee_buffer_units: int = 50_000,
    chain_id: int = 137,
    host: str = "https://clob.polymarket.com",
    rpc_url: str | None = None,
) -> dict:
    """One-call autonomous buyer onboarding for the POLY_1271 deposit wallet flow.

    Performs every step needed before a buyer can place orders:
      1. Derive deposit wallet address from the buyer's key
      2. Deploy the deposit wallet if not already deployed
      3. Ensure the buyer EOA has enough pUSD (wrap USDC.e if needed)
      4. Transfer pUSD from EOA to deposit wallet (order amount + fee buffer)
      5. Approve pUSD from deposit wallet to exchange_v2 via relayer
      6. Approve conditional tokens (setApprovalForAll) from deposit wallet via relayer
      7. Sync the CLOB balance/allowance cache

    Returns a summary dict with the deposit wallet address and each step's status.
    """
    from py_builder_relayer_client.client import RelayClient
    from py_builder_relayer_client.models import DepositWalletCall, TransactionType
    from py_clob_client_v2 import AssetType, BalanceAllowanceParams, ClobClient

    owner = signer.address()
    private_key = signer._account.key.hex()
    if not private_key.startswith("0x"):
        private_key = "0x" + private_key

    steps = []

    # --- 1. Derive deposit wallet ---
    owner_client = ClobClient(host=host, chain_id=chain_id, key=private_key)
    owner_creds = owner_client.create_or_derive_api_key()
    owner_client.set_api_creds(owner_creds)
    builder_creds = owner_client.create_builder_api_key()

    from py_builder_signing_sdk.config import BuilderApiKeyCreds, BuilderConfig
    builder_config = BuilderConfig(local_builder_creds=BuilderApiKeyCreds(
        key=builder_creds["key"],
        secret=builder_creds["secret"],
        passphrase=builder_creds["passphrase"],
    ))
    relayer = RelayClient(
        "https://relayer-v2.polymarket.com",
        chain_id,
        private_key,
        builder_config,
        rpc_url=rpc_url,
    )
    wallet = relayer.get_expected_deposit_wallet()
    steps.append({"step": "derive_wallet", "deposit_wallet": wallet})

    # --- 2. Deploy if needed ---
    if relayer.get_deployed(wallet, TransactionType.WALLET.value):
        steps.append({"step": "deploy", "status": "already_deployed"})
    else:
        response = relayer.deploy_deposit_wallet()
        confirmed = response.wait()
        if not confirmed:
            raise ExecutionError("deposit wallet deployment did not confirm")
        steps.append({"step": "deploy", "status": "deployed", "tx_id": response.transaction_id})

    # --- 3. Fund EOA with pUSD if needed ---
    total_needed = required_pusd_units + fee_buffer_units
    eoa_pusd = balance_of(rpc, PUSD, owner)
    if eoa_pusd < total_needed:
        eoa_usdce = balance_of(rpc, USDCE, owner)
        wrap_amount = total_needed - eoa_pusd
        if eoa_usdce < wrap_amount:
            raise ExecutionError(
                f"EOA has {eoa_pusd} pUSD and {eoa_usdce} USDC.e — "
                f"need {total_needed} pUSD total (order {required_pusd_units} + fee buffer {fee_buffer_units}). "
                "Fund the EOA with more USDC.e or pUSD before calling setup."
            )
        # Approve on-ramp and wrap
        if allowance(rpc, USDCE, owner, COLLATERAL_ONRAMP) < wrap_amount:
            approve_hash = signer.sign_and_send({
                "to": USDCE,
                "data": SEL_APPROVE + _addr(COLLATERAL_ONRAMP) + _uint(wrap_amount),
            })
            _wait_receipt(rpc, approve_hash)
        wrap_hash = signer.sign_and_send({
            "to": COLLATERAL_ONRAMP,
            "data": SEL_WRAP + _addr(USDCE) + _addr(owner) + _uint(wrap_amount),
        })
        _wait_receipt(rpc, wrap_hash)
        steps.append({"step": "wrap_usdce", "amount": wrap_amount, "tx": wrap_hash})
    else:
        steps.append({"step": "wrap_usdce", "status": "not_needed"})

    # --- 4. Transfer pUSD to deposit wallet ---
    wallet_pusd = balance_of(rpc, PUSD, wallet)
    if wallet_pusd < total_needed:
        transfer_amount = total_needed - wallet_pusd
        eoa_pusd_now = balance_of(rpc, PUSD, owner)
        if eoa_pusd_now < transfer_amount:
            raise ExecutionError(
                f"EOA pUSD {eoa_pusd_now} insufficient for transfer {transfer_amount} to deposit wallet"
            )
        transfer_hash = signer.sign_and_send({
            "to": PUSD,
            "data": SEL_TRANSFER + _addr(wallet) + _uint(transfer_amount),
        })
        _wait_receipt(rpc, transfer_hash)
        steps.append({"step": "transfer_pusd", "amount": transfer_amount, "tx": transfer_hash})
    else:
        steps.append({"step": "transfer_pusd", "status": "already_funded"})

    # --- 5. Approve pUSD from deposit wallet to exchange via relayer ---
    exchange = EXCHANGE_V2
    current_allowance = allowance(rpc, PUSD, wallet, exchange)
    if current_allowance < total_needed:
        nonce_payload = relayer.get_nonce(owner, TransactionType.WALLET.value)
        nonce = str(nonce_payload.get("nonce"))
        deadline = str(int(time.time()) + 900)
        call = DepositWalletCall(
            target=PUSD,
            value="0",
            data=SEL_APPROVE + _addr(exchange) + _uint(_MAX_UINT256),
        )
        response = relayer.execute_deposit_wallet_batch([call], wallet, nonce, deadline)
        confirmed = response.wait()
        if not confirmed:
            raise ExecutionError("deposit wallet pUSD approval did not confirm")
        steps.append({"step": "approve_pusd_exchange", "status": "approved", "tx_id": response.transaction_id})
    else:
        steps.append({"step": "approve_pusd_exchange", "status": "already_approved"})

    # --- 6. Approve conditional tokens (setApprovalForAll) for both exchanges ---
    for label, ex_addr in [("exchange_v2", EXCHANGE_V2), ("neg_risk_exchange_v2", NEG_RISK_EXCHANGE_V2)]:
        # Check isApprovedForAll(wallet, exchange) — selector 0xe985e9c5
        sel_is_approved = "0xe985e9c5"
        raw = rpc("eth_call", [{
            "to": CONDITIONAL_TOKENS,
            "data": sel_is_approved + _addr(wallet) + _addr(ex_addr),
        }, "latest"])
        approved = int(raw or "0x0", 16) != 0
        if not approved:
            nonce_payload = relayer.get_nonce(owner, TransactionType.WALLET.value)
            nonce = str(nonce_payload.get("nonce"))
            deadline = str(int(time.time()) + 900)
            call = DepositWalletCall(
                target=CONDITIONAL_TOKENS,
                value="0",
                data=SEL_SET_APPROVAL_FOR_ALL + _addr(ex_addr) + _uint(1),
            )
            response = relayer.execute_deposit_wallet_batch([call], wallet, nonce, deadline)
            confirmed = response.wait()
            if not confirmed:
                raise ExecutionError(f"conditional token approval for {label} did not confirm")
            steps.append({"step": f"approve_ct_{label}", "status": "approved", "tx_id": response.transaction_id})
        else:
            steps.append({"step": f"approve_ct_{label}", "status": "already_approved"})

    # --- 7. Sync CLOB balance cache ---
    trading_client = ClobClient(
        host=host,
        chain_id=chain_id,
        key=private_key,
        creds=owner_creds,
        signature_type=3,
        funder=wallet,
    )
    sync_result = trading_client.update_balance_allowance(
        BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
    )
    steps.append({"step": "sync_clob_cache", "result": str(sync_result)})

    return {
        "status": "ready",
        "buyer_eoa": owner,
        "deposit_wallet": wallet,
        "steps": steps,
    }


# ---------------------------------------------------------------- orders
def _default_clob_client(*, host: str, chain_id: int, private_key: str,
                         address: str, deposit_wallet: str | None = None):
    from py_clob_client_v2 import ClobClient

    return ClobClient(
        host=host,
        chain_id=chain_id,
        key=private_key,
        signature_type=3,
        funder=deposit_wallet or address,
    )


def _local_key_address(private_key: str) -> str:
    from eth_account import Account

    return Account.from_key(private_key).address


def _default_asp_post(url: str, payload: dict) -> dict:
    encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=encoded,
        headers={"content-type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=45) as response:
        return json.loads(response.read().decode("utf-8"))


class EoaOrderSubmitter:
    """Build and submit POLY_1271 (sig type 3) orders entirely in the buyer process.

    The deposit wallet is maker/funder; the buyer EOA key signs through the v2
    SDK's ERC-7739 wrapping. Credential-bearing values exist only in local
    variables sent to the ASP. The returned summary is allowlisted and cannot
    contain L2 credentials, signatures, HMACs, or the signed body.
    """

    def __init__(
        self,
        private_key: str,
        *,
        deposit_wallet: str | None = None,
        host: str = "https://clob.polymarket.com",
        chain_id: int = 137,
        client_factory=_default_clob_client,
        asp_post=_default_asp_post,
        address_deriver=_local_key_address,
        wallet_deriver=None,
    ):
        self._private_key = private_key
        self._address = address_deriver(private_key)
        self._deposit_wallet = deposit_wallet
        self._wallet_deriver = wallet_deriver
        self._host = host
        self._chain_id = chain_id
        self._client_factory = client_factory
        self._asp_post = asp_post

    @property
    def address(self) -> str:
        return self._address

    def submit(
        self,
        prepared: dict,
        *,
        side: str | None = None,
        operator_approval_id: str | None = None,
    ) -> dict:
        """Sign once, authenticate those exact bytes, and call submit-signed."""
        try:
            from py_clob_client_v2 import OrderArgs, OrderType, PartialCreateOrderOptions
            from py_clob_client_v2.endpoints import POST_ORDER
            from py_clob_client_v2.order_utils.model.order_data_v2 import order_to_json_v2
        except ImportError as exc:
            raise ExecutionError(
                "py_clob_client_v2 is required in the buyer execution environment"
            ) from exc

        intent = prepared.get("intent") or prepared
        # `intent.side` is the YES/NO outcome, not the venue order direction.
        order_side = (side or intent.get("order_side") or "BUY").upper()
        if order_side not in {"BUY", "SELL"}:
            raise ExecutionError("order side must be BUY or SELL")
        try:
            price = Decimal(str(intent["price"]))
            size = Decimal(str(intent["quantity"]))
        except (KeyError, InvalidOperation) as exc:
            raise ExecutionError("prepared intent has invalid price or quantity") from exc
        if price <= 0 or size <= 0:
            raise ExecutionError("order price and quantity must be positive")

        # Resolve deposit wallet: explicit > prepared > derive on demand
        dw = (
            self._deposit_wallet
            or (prepared.get("deposit_wallet"))
            or (intent.get("deposit_wallet"))
        )
        if not dw and self._wallet_deriver:
            dw = self._wallet_deriver(self._private_key)
        if not dw:
            raise ExecutionError(
                "deposit wallet is required for POLY_1271 orders — pass deposit_wallet "
                "to EoaOrderSubmitter or include it in the prepared intent"
            )

        client = self._client_factory(
            host=self._host,
            chain_id=self._chain_id,
            private_key=self._private_key,
            address=self._address,
            deposit_wallet=dw,
        )
        creds = client.create_or_derive_api_key()
        client.set_api_creds(creds)
        token_id = str(intent["token_id"])
        # Prefer tick_size and neg_risk from the prepared intent (already
        # validated by TrueOdds) to avoid a redundant live CLOB query.
        pre_trade = prepared.get("pre_trade") or {}
        tick = pre_trade.get("validated_against_tick") or intent.get("tick_size")
        neg = intent.get("neg_risk")
        options = PartialCreateOrderOptions(
            tick_size=tick if tick is not None else client.get_tick_size(token_id),
            neg_risk=neg if neg is not None else client.get_neg_risk(token_id),
        )
        order = client.create_order(
            OrderArgs(
                token_id=token_id,
                price=float(price),
                size=float(size),
                side=order_side,
            ),
            options,
        )
        if int(order.signatureType) != 3:
            raise ExecutionError("buyer SDK produced a non-POLY_1271 order (expected sig type 3)")
        # POLY_1271: maker = deposit wallet (funder), signer = EOA key holder
        if str(order.maker).lower() != dw.lower():
            raise ExecutionError("order maker does not match the deposit wallet")
        if str(order.signer).lower() != self._address.lower():
            raise ExecutionError("order signer does not match the buyer EOA")

        order_type = getattr(OrderType, str(intent.get("time_in_force") or "GTC"))
        body = order_to_json_v2(order, creds.api_key or "", order_type)
        serialized = json.dumps(body, separators=(",", ":"), ensure_ascii=False)
        body_bytes = serialized.encode("utf-8")
        headers = dict(
            client._l2_headers(
                "POST",
                POST_ORDER,
                body=body,
                serialized_body=serialized,
            )
        )
        submit_url = (
            ((prepared.get("client_execution") or {}).get("submit_signed") or {}).get("url")
        )
        if not submit_url:
            raise ExecutionError("prepared response has no submit-signed URL")
        try:
            response = self._asp_post(
                submit_url,
                {
                    "body_base64": base64.b64encode(body_bytes).decode("ascii"),
                    "headers": headers,
                    **(
                        {"operator_approval_id": operator_approval_id}
                        if operator_approval_id else {}
                    ),
                },
            )
        except Exception as exc:
            raise ExecutionError("submit-signed request failed; sensitive response omitted") from exc

        intent_result = response.get("intent") if isinstance(response, dict) else None
        result = intent_result if isinstance(intent_result, dict) else response
        if not isinstance(result, dict):
            raise ExecutionError("submit-signed returned an invalid response")
        return {
            key: result[key]
            for key in ("intent_id", "state", "venue_order_id", "message")
            if key in result
        } | {
            "side": order_side,
            "body_sha256": hashlib.sha256(body_bytes).hexdigest(),
        }

    def buyer_control_authorization(
        self,
        buyer_id: str,
        *,
        action: str,
        reason: str,
        timestamp: int | None = None,
        nonce: str | None = None,
    ) -> dict:
        """Create a one-shot EOA authorization for emergency stop or clear."""
        if action not in {"cancel_only", "clear"}:
            raise ExecutionError("buyer control action must be cancel_only or clear")
        timestamp = int(time.time()) if timestamp is None else timestamp
        nonce = nonce or uuid.uuid4().hex
        message = "\n".join((
            "TrueOdds ASP buyer control v1",
            f"buyer_id:{buyer_id}",
            f"action:{action}",
            f"timestamp:{timestamp}",
            f"nonce:{nonce}",
            f"reason:{reason}",
        ))
        from eth_account.messages import encode_defunct

        signature = self._account_for_control().sign_message(
            encode_defunct(text=message)
        ).signature.hex()
        return {
            "buyer_address": self._address,
            "action": action,
            "reason": reason,
            "timestamp": timestamp,
            "nonce": nonce,
            "signature": signature if signature.startswith("0x") else f"0x{signature}",
        }

    def _account_for_control(self):
        from eth_account import Account

        return Account.from_key(self._private_key)

    def submit_emergency_cancellation(
        self,
        *,
        buyer_id: str,
        asp_url: str,
        intents: list[dict],
    ) -> dict:
        """Authenticate exact venue order IDs locally and relay cancellation."""
        try:
            from py_clob_client_v2.endpoints import CANCEL_ORDERS
        except ImportError as exc:
            raise ExecutionError(
                "py_clob_client_v2 is required in the buyer execution environment"
            ) from exc
        if not intents or any(
            not item.get("intent_id") or not item.get("venue_order_id") for item in intents
        ):
            raise ExecutionError("emergency cancellation requires resolved intent and venue order IDs")
        client = self._client_factory(
            host=self._host,
            chain_id=self._chain_id,
            private_key=self._private_key,
            address=self._address,
            deposit_wallet=self._deposit_wallet,
        )
        creds = client.create_or_derive_api_key()
        client.set_api_creds(creds)
        order_ids = [str(item["venue_order_id"]) for item in intents]
        serialized = json.dumps(order_ids, separators=(",", ":"), ensure_ascii=False)
        headers = dict(client._l2_headers(
            "DELETE", CANCEL_ORDERS, body=order_ids, serialized_body=serialized
        ))
        try:
            response = self._asp_post(
                asp_url,
                {
                    "body_base64": base64.b64encode(serialized.encode("utf-8")).decode("ascii"),
                    "headers": headers,
                    "intent_ids": [str(item["intent_id"]) for item in intents],
                },
            )
        except Exception as exc:
            raise ExecutionError(
                "emergency cancellation relay failed; sensitive response omitted"
            ) from exc
        if not isinstance(response, dict):
            raise ExecutionError("emergency cancellation returned an invalid response")
        return {
            key: response[key]
            for key in (
                "buyer_id", "mode", "cancelled_intents", "remaining_intents", "body_sha256"
            )
            if key in response
        }
