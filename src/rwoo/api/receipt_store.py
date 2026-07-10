"""Decision receipts and idempotency.

Every priced or refused decision commits one receipt to an append-only,
hash-chained ledger (rwoo.receipts.AppendOnlyLedger). The receipt binds the
request id, service, request hash, market/event ids, rule hash, model version,
the probability *or* refusal, interval, confidence, economics, why-trace,
calibration scope, source freshness, time, and payment reference (when present)
into a keccak256 record whose chain hash makes after-the-fact rewriting
detectable. No private payment data is ever committed.

Idempotency is in-process and keyed by the client's Idempotency-Key: replaying
the same key returns the stored response and does NOT append a second receipt
(and, once payments are live, must not double-charge).
"""
from __future__ import annotations

import threading
from typing import Any

from rwoo.receipts import AppendOnlyLedger, ReceiptRecord, hash_hex

DECISION_RECORD_TYPE = "oracle_decision"


class DecisionReceiptStore:
    def __init__(self, ledger_path) -> None:
        self.ledger = AppendOnlyLedger(ledger_path)
        self._lock = threading.Lock()

    def commit(self, payload: dict[str, Any]) -> ReceiptRecord:
        # The ledger reads the whole file, computes the chain hash, and appends
        # atomically; the lock serializes concurrent writers in-process so two
        # requests can't both read sequence N and both write it.
        with self._lock:
            return self.ledger.append(DECISION_RECORD_TYPE, payload)

    def find(self, record_hash: str) -> ReceiptRecord | None:
        for record in self.ledger.read_records():
            if record.record_hash == record_hash:
                return record
        return None

    def verify(self) -> dict[str, Any]:
        return self.ledger.verify()


class IdempotencyCache:
    """In-process idempotency store. Keys are opaque client-supplied strings."""

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            return self._store.get(key)

    def put(self, key: str, response: dict[str, Any]) -> None:
        with self._lock:
            self._store[key] = response


def request_hash(payload: dict[str, Any]) -> str:
    """Canonical keccak256 of a request body, used as the receipt's request
    commitment and as a stable idempotency fallback key."""
    return hash_hex(payload)
