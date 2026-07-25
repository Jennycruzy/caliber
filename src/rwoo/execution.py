"""Crash-safe prediction-market execution primitives.

The module deliberately separates intent persistence from venue connectivity.
No signing secret is accepted or stored here.  A live adapter must be supplied
by the operator; the default adapter always fails closed.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from pathlib import Path
from typing import Any, Protocol


TERMINAL_STATES = {"FILLED", "CANCELLED", "REJECTED", "EXPIRED"}
TRANSITIONS = {
    "PREPARED": {"SUBMITTING", "CANCELLED"},
    "SUBMITTING": {"OPEN", "PARTIALLY_FILLED", "FILLED", "REJECTED", "UNKNOWN"},
    "UNKNOWN": {"UNKNOWN", "OPEN", "PARTIALLY_FILLED", "FILLED", "REJECTED", "CANCELLED", "EXPIRED"},
    "OPEN": {"OPEN", "PARTIALLY_FILLED", "FILLED", "CANCELLING", "CANCELLED", "EXPIRED", "UNKNOWN"},
    "PARTIALLY_FILLED": {"PARTIALLY_FILLED", "FILLED", "CANCELLING", "CANCELLED", "EXPIRED", "UNKNOWN"},
    "CANCELLING": {"CANCELLED", "FILLED", "PARTIALLY_FILLED", "UNKNOWN"},
}


class ExecutionError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def exact_decimal(value: str, *, name: str, scale: int, minimum: Decimal,
                  maximum: Decimal | None = None) -> Decimal:
    if not isinstance(value, str):
        raise ExecutionError("INVALID_EXECUTION", f"{name} must be a decimal string")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ExecutionError("INVALID_EXECUTION", f"{name} is not a valid decimal") from exc
    quantum = Decimal(1).scaleb(-scale)
    if not number.is_finite() or number < minimum or (maximum is not None and number > maximum):
        raise ExecutionError("INVALID_EXECUTION", f"{name} is outside its allowed range")
    if number.quantize(quantum, rounding=ROUND_DOWN) != number:
        raise ExecutionError("INVALID_EXECUTION", f"{name} supports at most {scale} decimal places")
    return number


def canonical(number: Decimal) -> str:
    rendered = format(number, "f")
    return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered


@dataclass(frozen=True)
class VenueResult:
    state: str
    venue_order_id: str | None = None
    filled_quantity: str = "0"
    average_fill_price: str | None = None
    message: str | None = None


class ExecutionAdapter(Protocol):
    def submit(self, intent: dict[str, Any]) -> VenueResult: ...
    def cancel(self, intent: dict[str, Any]) -> VenueResult: ...
    def reconcile(self, intent: dict[str, Any]) -> VenueResult: ...


class DisabledExecutionAdapter:
    def _blocked(self) -> VenueResult:
        raise ExecutionError("EXECUTION_DISABLED", "live venue adapter is not configured")

    def submit(self, intent: dict[str, Any]) -> VenueResult:
        return self._blocked()

    def cancel(self, intent: dict[str, Any]) -> VenueResult:
        return self._blocked()

    def reconcile(self, intent: dict[str, Any]) -> VenueResult:
        return self._blocked()


class ExecutionStore:
    """Transactional intent/event store. SQLite uniqueness is the idempotency lock."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self):
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS execution_intents (
                    intent_id TEXT PRIMARY KEY, idempotency_key TEXT NOT NULL UNIQUE,
                    request_hash TEXT NOT NULL, state TEXT NOT NULL, venue TEXT NOT NULL,
                    market_id TEXT NOT NULL, token_id TEXT NOT NULL, side TEXT NOT NULL,
                    price TEXT NOT NULL, quantity TEXT NOT NULL, notional TEXT NOT NULL,
                    order_type TEXT NOT NULL, time_in_force TEXT NOT NULL,
                    decision_receipt_hash TEXT, event_group_id TEXT NOT NULL,
                    operator_approval_id TEXT, venue_order_id TEXT,
                    filled_quantity TEXT NOT NULL DEFAULT '0', average_fill_price TEXT,
                    last_error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS execution_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT, intent_id TEXT NOT NULL,
                    from_state TEXT, to_state TEXT NOT NULL, detail TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(intent_id) REFERENCES execution_intents(intent_id)
                );
                CREATE INDEX IF NOT EXISTS execution_events_intent
                    ON execution_events(intent_id, sequence);
                CREATE TABLE IF NOT EXISTS signed_order_submissions (
                    body_hash TEXT PRIMARY KEY,
                    intent_id TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(intent_id) REFERENCES execution_intents(intent_id)
                );
                CREATE TABLE IF NOT EXISTS execution_buyers (
                    buyer_id TEXT PRIMARY KEY, address TEXT NOT NULL UNIQUE,
                    kill_switch_active INTEGER NOT NULL DEFAULT 0,
                    kill_switch_reason TEXT, kill_switch_updated_at TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS execution_signal_refs (
                    signal_id TEXT PRIMARY KEY, buyer_id TEXT NOT NULL,
                    payload TEXT NOT NULL, expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(buyer_id) REFERENCES execution_buyers(buyer_id)
                );
                CREATE TABLE IF NOT EXISTS buyer_control_nonces (
                    buyer_id TEXT NOT NULL, nonce TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(buyer_id, nonce),
                    FOREIGN KEY(buyer_id) REFERENCES execution_buyers(buyer_id)
                );
                CREATE TABLE IF NOT EXISTS signed_cancel_submissions (
                    body_hash TEXT PRIMARY KEY, buyer_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(buyer_id) REFERENCES execution_buyers(buyer_id)
                );
            """)
            existing = {
                row["name"] for row in db.execute("PRAGMA table_info(execution_intents)").fetchall()
            }
            for name, declaration in (
                ("buyer_id", "TEXT"),
                ("signal_id", "TEXT"),
                ("signal_expires_at", "TEXT"),
                ("exit_policy", "TEXT"),
                ("position_id", "TEXT"),
                ("order_direction", "TEXT"),
            ):
                if name not in existing:
                    db.execute(f"ALTER TABLE execution_intents ADD COLUMN {name} {declaration}")

    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        return dict(row) if row else None

    def get(self, intent_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = self._row(db.execute(
                "SELECT * FROM execution_intents WHERE intent_id=?", (intent_id,)
            ).fetchone())
            if row:
                row["events"] = [dict(event) for event in db.execute(
                    "SELECT sequence,from_state,to_state,detail,created_at FROM execution_events "
                    "WHERE intent_id=? ORDER BY sequence", (intent_id,)
                ).fetchall()]
                for event in row["events"]:
                    event["detail"] = json.loads(event["detail"])
            return row

    def prepare(self, values: dict[str, Any], idempotency_key: str, request_hash: str) -> tuple[dict[str, Any], bool]:
        now = datetime.now(timezone.utc).isoformat()
        intent_id = f"ex_{uuid.uuid4().hex}"
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT intent_id,request_hash FROM execution_intents WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
            if existing:
                if existing["request_hash"] != request_hash:
                    raise ExecutionError("IDEMPOTENCY_CONFLICT", "execution idempotency key is bound to another request")
                return self.get(existing["intent_id"]), True
            columns = ["intent_id", "idempotency_key", "request_hash", "state", *values.keys(), "created_at", "updated_at"]
            params = [intent_id, idempotency_key, request_hash, "PREPARED", *values.values(), now, now]
            db.execute(
                f"INSERT INTO execution_intents ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                params,
            )
            db.execute(
                "INSERT INTO execution_events(intent_id,from_state,to_state,detail,created_at) VALUES(?,?,?,?,?)",
                (intent_id, None, "PREPARED", "{}", now),
            )
        return self.get(intent_id), False

    def transition(self, intent_id: str, expected: set[str], target: str, *, detail: dict[str, Any] | None = None,
                   updates: dict[str, Any] | None = None) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT state FROM execution_intents WHERE intent_id=?", (intent_id,)).fetchone()
            if not row:
                raise ExecutionError("EXECUTION_NOT_FOUND", "execution intent was not found")
            current = row["state"]
            if current not in expected or target not in TRANSITIONS.get(current, set()):
                raise ExecutionError("INVALID_EXECUTION_STATE", f"cannot transition execution from {current} to {target}")
            fields = {"state": target, "updated_at": now, **(updates or {})}
            db.execute(
                f"UPDATE execution_intents SET {','.join(f'{key}=?' for key in fields)} WHERE intent_id=?",
                [*fields.values(), intent_id],
            )
            db.execute(
                "INSERT INTO execution_events(intent_id,from_state,to_state,detail,created_at) VALUES(?,?,?,?,?)",
                (intent_id, current, target, json.dumps(detail or {}, sort_keys=True), now),
            )
        return self.get(intent_id)

    def reserve_signed_submission(self, intent_id: str, body_hash: str) -> None:
        """Burn a signed order body for one intent before relay.

        This protects both axes: the same signed bytes cannot be replayed
        against another intent, and one intent cannot be submitted twice with
        two different signed bodies.
        """
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT 1 FROM execution_intents WHERE intent_id=?", (intent_id,)).fetchone():
                raise ExecutionError("EXECUTION_NOT_FOUND", "execution intent was not found")
            try:
                db.execute(
                    "INSERT INTO signed_order_submissions(body_hash,intent_id,created_at) VALUES(?,?,?)",
                    (body_hash, intent_id, now),
                )
            except sqlite3.IntegrityError as exc:
                raise ExecutionError("SIGNED_ORDER_REPLAY", "signed order payload was already used") from exc

    def signed_submission_exists(self, body_hash: str) -> bool:
        with self._connect() as db:
            return db.execute(
                "SELECT 1 FROM signed_order_submissions WHERE body_hash=?",
                (body_hash,),
            ).fetchone() is not None

    def buyer(self, address: str) -> dict[str, Any]:
        normalized = address.lower()
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._connect() as db:
            buyer_id = f"byr_{uuid.uuid4().hex}"
            db.execute(
                "INSERT OR IGNORE INTO execution_buyers(buyer_id,address,created_at) VALUES(?,?,?)",
                (buyer_id, normalized, now),
            )
            row = db.execute(
                "SELECT * FROM execution_buyers WHERE address=?", (normalized,)
            ).fetchone()
        if not row:
            raise ExecutionError("BUYER_NOT_FOUND", "buyer could not be created")
        return dict(row)

    def create_signal_ref(
        self, buyer_id: str, payload: dict[str, Any], expires_at: str
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        signal_id = f"sig_{uuid.uuid4().hex}"
        with self._connect() as db:
            db.execute(
                "INSERT INTO execution_signal_refs(signal_id,buyer_id,payload,expires_at,created_at) "
                "VALUES(?,?,?,?,?)",
                (signal_id, buyer_id, json.dumps(payload, sort_keys=True), expires_at, now),
            )
        return {
            "signal_id": signal_id,
            "buyer_id": buyer_id,
            "payload": payload,
            "expires_at": expires_at,
        }

    def signal_ref(self, signal_id: str, buyer_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM execution_signal_refs WHERE signal_id=? AND buyer_id=?",
                (signal_id, buyer_id),
            ).fetchone()
        if not row:
            return None
        value = dict(row)
        value["payload"] = json.loads(value["payload"])
        return value

    def buyer_intents(self, buyer_id: str) -> list[dict[str, Any]]:
        with self._connect() as db:
            ids = [
                row["intent_id"] for row in db.execute(
                    "SELECT intent_id FROM execution_intents WHERE buyer_id=? ORDER BY created_at",
                    (buyer_id,),
                ).fetchall()
            ]
        return [intent for intent_id in ids if (intent := self.get(intent_id))]

    def set_kill_switch(self, buyer_id: str, *, active: bool, reason: str) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as db:
            updated = db.execute(
                "UPDATE execution_buyers SET kill_switch_active=?,kill_switch_reason=?,"
                "kill_switch_updated_at=? WHERE buyer_id=?",
                (1 if active else 0, reason, now, buyer_id),
            )
            if updated.rowcount != 1:
                raise ExecutionError("BUYER_NOT_FOUND", "buyer was not found")
        return self.buyer_by_id(buyer_id)

    def buyer_by_id(self, buyer_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM execution_buyers WHERE buyer_id=?", (buyer_id,)
            ).fetchone()
        return dict(row) if row else None

    def consume_control_nonce(self, buyer_id: str, nonce: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        try:
            with self._connect() as db:
                db.execute(
                    "INSERT INTO buyer_control_nonces(buyer_id,nonce,created_at) VALUES(?,?,?)",
                    (buyer_id, nonce, now),
                )
        except sqlite3.IntegrityError as exc:
            raise ExecutionError("CONTROL_REPLAY", "buyer control authorization was already used") from exc

    def set_position_id(self, intent_id: str, position_id: str) -> None:
        """Link an intent to its PositionStore position after creation."""
        with self._connect() as db:
            db.execute(
                "UPDATE execution_intents SET position_id=?,updated_at=? WHERE intent_id=?",
                (position_id, datetime.now(timezone.utc).isoformat(), intent_id),
            )

    def reserve_signed_cancel(self, buyer_id: str, body_hash: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        try:
            with self._connect() as db:
                db.execute(
                    "INSERT INTO signed_cancel_submissions(body_hash,buyer_id,created_at) VALUES(?,?,?)",
                    (body_hash, buyer_id, now),
                )
        except sqlite3.IntegrityError as exc:
            raise ExecutionError("SIGNED_CANCEL_REPLAY", "signed cancellation was already used") from exc


class ExecutionCoordinator:
    def __init__(self, store: ExecutionStore, *, mode: str = "disabled",
                 adapter: ExecutionAdapter | None = None, max_order_usd: str = "10.00",
                 position_store=None):
        if mode not in {"disabled", "certification", "live"}:
            raise ValueError("execution mode must be disabled, certification, or live")
        self.store = store
        self.mode = mode
        self.adapter = adapter or DisabledExecutionAdapter()
        self.max_order = exact_decimal(max_order_usd, name="max_order_usd", scale=6, minimum=Decimal("0.01"))
        self.position_store = position_store

    @property
    def live_enabled(self) -> bool:
        return self.mode == "live" and not isinstance(self.adapter, DisabledExecutionAdapter)

    def prepare(self, payload: dict[str, Any], idempotency_key: str) -> tuple[dict[str, Any], bool]:
        if not idempotency_key or len(idempotency_key) > 200:
            raise ExecutionError("INVALID_EXECUTION", "a 1-200 character idempotency key is required")
        if payload.get("venue") != "polymarket":
            raise ExecutionError("INVALID_EXECUTION", "the execution adapter currently supports polymarket only")
        if payload.get("side") not in {"YES", "NO"}:
            raise ExecutionError("INVALID_EXECUTION", "side must be YES or NO")
        price = exact_decimal(payload.get("price"), name="price", scale=6,
                              minimum=Decimal("0.000001"), maximum=Decimal("0.999999"))
        quantity = exact_decimal(payload.get("quantity"), name="quantity", scale=6, minimum=Decimal("0.000001"))
        notional = price * quantity
        if notional > self.max_order:
            raise ExecutionError("RISK_LIMIT_EXCEEDED", "order notional exceeds the configured per-order limit")
        for required in ("market_id", "token_id", "event_group_id"):
            if not str(payload.get(required) or "").strip():
                raise ExecutionError("INVALID_EXECUTION", f"{required} is required")
        normalized = {
            "venue": "polymarket", "market_id": payload["market_id"].strip(),
            "token_id": payload["token_id"].strip(), "side": payload["side"],
            "price": canonical(price), "quantity": canonical(quantity),
            "notional": canonical(notional), "order_type": "LIMIT",
            "time_in_force": payload.get("time_in_force", "GTC"),
            "decision_receipt_hash": payload.get("decision_receipt_hash"),
            "event_group_id": payload["event_group_id"].strip(),
            "buyer_id": payload.get("buyer_id"),
            "signal_id": payload.get("signal_id"),
            "signal_expires_at": payload.get("signal_expires_at"),
            "exit_policy": (
                json.dumps(payload.get("exit_policy"), sort_keys=True)
                if payload.get("exit_policy") is not None else None
            ),
        }
        if normalized["time_in_force"] not in {"GTC", "GTD", "FOK", "FAK"}:
            raise ExecutionError("INVALID_EXECUTION", "unsupported time_in_force")
        digest = hashlib.sha256(json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if normalized["buyer_id"]:
            buyer = self.store.buyer_by_id(normalized["buyer_id"])
            if not buyer:
                raise ExecutionError("BUYER_NOT_FOUND", "buyer was not found")
            if buyer["kill_switch_active"]:
                raise ExecutionError("BUYER_KILL_SWITCH", "buyer emergency stop is active")

        # Position metadata — added after hash so order_direction and
        # system-generated position_id don't change idempotency identity.
        order_direction = payload.get("order_direction")
        if normalized["exit_policy"] and not order_direction:
            order_direction = "BUY"
        normalized["order_direction"] = order_direction
        normalized["position_id"] = payload.get("position_id")

        intent, is_replay = self.store.prepare(normalized, idempotency_key, digest)

        if (
            not is_replay
            and self.position_store is not None
            and order_direction == "BUY"
            and normalized["exit_policy"]
        ):
            from rwoo.position_monitor import ExitPolicy

            position_id = f"pos_{uuid.uuid4().hex}"
            exit_policy_data = json.loads(normalized["exit_policy"])
            self.position_store.create(
                position_id=position_id,
                token_id=normalized["token_id"],
                entry_order_id=intent["intent_id"],
                target_quantity=normalized["quantity"],
                policy=ExitPolicy(**exit_policy_data),
            )
            self.store.set_position_id(intent["intent_id"], position_id)
            intent = self.store.get(intent["intent_id"])

        return intent, is_replay

    def submit(self, intent_id: str, operator_approval_id: str) -> dict[str, Any]:
        intent = self.store.get(intent_id)
        if not intent:
            raise ExecutionError("EXECUTION_NOT_FOUND", "execution intent was not found")
        if not self.live_enabled:
            raise ExecutionError("EXECUTION_DISABLED", "funded execution is locked; prepare and inspect are available")
        if not operator_approval_id.strip():
            raise ExecutionError("APPROVAL_REQUIRED", "explicit operator approval is required")
        # Revalidate against the live venue BEFORE committing to SUBMITTING, so a
        # transient or binding failure keeps the intent PREPARED and retryable
        # rather than being misreported as an ambiguous venue outcome.
        self._pre_submit_validate(intent)
        intent = self.store.transition(intent_id, {"PREPARED"}, "SUBMITTING",
                                       updates={"operator_approval_id": operator_approval_id})
        try:
            result = self.adapter.submit(intent)
        except ExecutionError as exc:
            # Contract: an adapter/signer raises ExecutionError only for a
            # pre-transmission refusal (final revalidation, missing signer, or a
            # pre-send balance/allowance check). Nothing reached the venue, so
            # this is a clean rejection — never an ambiguous UNKNOWN.
            return self.store.transition(intent_id, {"SUBMITTING"}, "REJECTED",
                                         detail={"code": exc.code, "reason": "pre_transmission_refusal"},
                                         updates={"last_error": str(exc)})
        except Exception as exc:
            # Any other failure may follow transmission and cannot be treated as
            # a rejection; it must reconcile before any resubmission.
            return self.store.transition(intent_id, {"SUBMITTING"}, "UNKNOWN",
                                         detail={"reason": type(exc).__name__},
                                         updates={"last_error": "venue outcome unknown; reconciliation required"})
        return self._apply_result(intent_id, {"SUBMITTING"}, result)

    def submit_signed(
        self, intent_id: str, body_hash: str, relay, operator_approval_id: str | None = None
    ) -> dict[str, Any]:
        """Relay a caller-signed order without server-side signing authority."""
        intent = self.store.get(intent_id)
        if not intent:
            raise ExecutionError("EXECUTION_NOT_FOUND", "execution intent was not found")
        if intent["state"] != "PREPARED":
            if self.store.signed_submission_exists(body_hash):
                raise ExecutionError("SIGNED_ORDER_REPLAY", "signed order payload was already used")
            raise ExecutionError("INVALID_EXECUTION_STATE", f"cannot submit signed order from {intent['state']}")
        if intent.get("buyer_id"):
            buyer = self.store.buyer_by_id(intent["buyer_id"])
            if not buyer or buyer["kill_switch_active"]:
                raise ExecutionError("BUYER_KILL_SWITCH", "buyer emergency stop is active")
            if not str(operator_approval_id or "").strip():
                raise ExecutionError("APPROVAL_REQUIRED", "explicit buyer approval is required")
            if intent.get("signal_id"):
                try:
                    expires_at = datetime.fromisoformat(
                        str(intent.get("signal_expires_at") or "").replace("Z", "+00:00")
                    )
                except ValueError as exc:
                    raise ExecutionError("SIGNAL_EXPIRED", "signal expiration is invalid") from exc
                if datetime.now(timezone.utc) >= expires_at.astimezone(timezone.utc):
                    raise ExecutionError("SIGNAL_EXPIRED", "signal expired before signed submission")
        # Validate before burning the signature so malformed payloads can be
        # corrected by the caller without consuming the one-shot replay slot.
        self._pre_submit_validate(intent)
        self.store.reserve_signed_submission(intent_id, body_hash)
        intent = self.store.transition(
            intent_id,
            {"PREPARED"},
            "SUBMITTING",
            detail={"submission": "caller_signed", "body_hash": body_hash},
            updates={"operator_approval_id": operator_approval_id},
        )
        try:
            result = relay(intent)
        except ExecutionError as exc:
            return self.store.transition(
                intent_id,
                {"SUBMITTING"},
                "REJECTED",
                detail={"code": exc.code, "reason": "signed_submission_refusal"},
                updates={"last_error": str(exc)},
            )
        except Exception as exc:
            return self.store.transition(
                intent_id,
                {"SUBMITTING"},
                "UNKNOWN",
                detail={"reason": type(exc).__name__, "body_hash": body_hash},
                updates={"last_error": "venue outcome unknown; reconciliation required"},
            )
        return self._apply_result(intent_id, {"SUBMITTING"}, result)

    def _pre_submit_validate(self, intent: dict[str, Any]) -> None:
        """Run an adapter's optional read-only pre-trade gate before submission.

        Adapters expose ``validate(intent)`` to re-check market status, token
        binding, tick size, book freshness, and depth. A failure here leaves the
        intent PREPARED. Adapters without the hook (e.g. the disabled default)
        are skipped.
        """
        validate = getattr(self.adapter, "validate", None)
        if validate is None:
            return
        try:
            validate(intent)
        except ExecutionError:
            raise
        except Exception as exc:
            raise ExecutionError("PRE_TRADE_CHECK_FAILED",
                                 f"pre-trade validation failed: {type(exc).__name__}") from exc

    def reconcile(self, intent_id: str) -> dict[str, Any]:
        intent = self.store.get(intent_id)
        if not intent:
            raise ExecutionError("EXECUTION_NOT_FOUND", "execution intent was not found")
        if not self.live_enabled:
            raise ExecutionError("EXECUTION_DISABLED", "live reconciliation adapter is not configured")
        result = self.adapter.reconcile(intent)
        return self._apply_result(intent_id, {intent["state"]}, result)

    def cancel(self, intent_id: str) -> dict[str, Any]:
        intent = self.store.get(intent_id)
        if not intent:
            raise ExecutionError("EXECUTION_NOT_FOUND", "execution intent was not found")
        if intent["state"] == "PREPARED":
            return self.store.transition(intent_id, {"PREPARED"}, "CANCELLED",
                                         detail={"reason": "cancelled before submission"})
        if intent["state"] in TERMINAL_STATES:
            return intent
        if not self.live_enabled:
            raise ExecutionError("EXECUTION_DISABLED", "live cancellation adapter is not configured")
        intent = self.store.transition(intent_id, {"OPEN", "PARTIALLY_FILLED"}, "CANCELLING")
        try:
            result = self.adapter.cancel(intent)
        except Exception as exc:
            return self.store.transition(intent_id, {"CANCELLING"}, "UNKNOWN",
                                         detail={"reason": type(exc).__name__},
                                         updates={"last_error": "cancellation outcome unknown; reconciliation required"})
        return self._apply_result(intent_id, {"CANCELLING"}, result)

    def _apply_result(self, intent_id: str, expected: set[str], result: VenueResult) -> dict[str, Any]:
        if result.state not in {"OPEN", "PARTIALLY_FILLED", "FILLED", "REJECTED", "CANCELLED", "EXPIRED", "UNKNOWN"}:
            raise ExecutionError("INVALID_VENUE_RESPONSE", "adapter returned an invalid state")
        intent = self.store.transition(intent_id, expected, result.state, detail=asdict(result), updates={
            "venue_order_id": result.venue_order_id,
            "filled_quantity": result.filled_quantity,
            "average_fill_price": result.average_fill_price,
            "last_error": result.message,
        })
        self._bind_position_fill(intent, result)
        return intent

    def _bind_position_fill(self, intent: dict[str, Any], result: VenueResult) -> None:
        """Push confirmed fills into the PositionStore if one is configured.

        Called after every venue result. Only acts when there are actual fills
        (filled_quantity > 0) and the intent is linked to a position.
        """
        if self.position_store is None:
            return
        position_id = intent.get("position_id")
        direction = intent.get("order_direction")
        if not position_id or not direction:
            return
        filled = Decimal(result.filled_quantity or "0")
        if filled <= 0:
            return
        import time as _time

        if direction == "BUY":
            self.position_store.reconcile_entry(
                position_id,
                cumulative_filled=result.filled_quantity,
                average_price=result.average_fill_price or "0",
                observed_ts=int(_time.time()),
            )
        elif direction == "SELL":
            self.position_store.reconcile_exit(
                position_id,
                cumulative_filled=result.filled_quantity,
            )
