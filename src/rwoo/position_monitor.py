"""Crash-safe buyer-position state and deterministic autonomous exit policy."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ExitPolicy:
    take_profit_pct: str
    stop_loss_pct: str
    max_hold_seconds: int
    max_exit_slippage_bps: int
    invalidation_rule: str | None = None

    def validate(self) -> None:
        tp, sl = Decimal(self.take_profit_pct), Decimal(self.stop_loss_pct)
        if not Decimal("0.1") <= tp <= Decimal("500"):
            raise ValueError("take_profit_pct must be between 0.1 and 500")
        if not Decimal("0.1") <= sl < Decimal("100"):
            raise ValueError("stop_loss_pct must be between 0.1 and 100")
        if not 60 <= self.max_hold_seconds <= 31_536_000:
            raise ValueError("max_hold_seconds must be between 60 and 31536000")
        if not 1 <= self.max_exit_slippage_bps <= 500:
            raise ValueError("max_exit_slippage_bps must be between 1 and 500")


def exit_trigger(position: dict[str, Any], *, executable_bid: Decimal,
                 invalidated: bool, now_ts: int, kill_switch: bool = False) -> str | None:
    """Return the highest-priority exit reason using executable bid economics."""
    policy = ExitPolicy(**json.loads(position["policy_json"]))
    entry = Decimal(position["average_entry_price"])
    if kill_switch:
        return "KILL_SWITCH"
    if invalidated:
        return "INVALIDATION"
    if executable_bid <= entry * (Decimal(1) - Decimal(policy.stop_loss_pct) / 100):
        return "STOP_LOSS"
    if now_ts >= int(position["first_fill_ts"]) + policy.max_hold_seconds:
        return "TIME_EXIT"
    if executable_bid >= entry * (Decimal(1) + Decimal(policy.take_profit_pct) / 100):
        return "TAKE_PROFIT"
    return None


class PositionStore:
    """SQLite-backed cumulative-fill ledger; safe to reopen after a crash."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS positions (
                    position_id TEXT PRIMARY KEY, token_id TEXT NOT NULL,
                    entry_order_id TEXT NOT NULL UNIQUE, target_quantity TEXT NOT NULL,
                    entry_filled TEXT NOT NULL DEFAULT '0',
                    average_entry_price TEXT, exit_filled TEXT NOT NULL DEFAULT '0',
                    policy_json TEXT NOT NULL, first_fill_ts INTEGER,
                    status TEXT NOT NULL DEFAULT 'ENTRY_OPEN',
                    exit_reason TEXT, exit_order_id TEXT UNIQUE,
                    updated_at TEXT NOT NULL
                );
            """)

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        return db

    def get(self, position_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM positions WHERE position_id=?", (position_id,)).fetchone()
        return dict(row) if row else None

    def create(self, *, position_id: str, token_id: str, entry_order_id: str,
               target_quantity: str, policy: ExitPolicy) -> dict[str, Any]:
        policy.validate()
        quantity = Decimal(target_quantity)
        if quantity <= 0:
            raise ValueError("target_quantity must be positive")
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as db:
            db.execute(
                "INSERT INTO positions(position_id,token_id,entry_order_id,target_quantity,"
                "policy_json,updated_at) VALUES(?,?,?,?,?,?)",
                (position_id, token_id, entry_order_id, str(quantity),
                 json.dumps(asdict(policy), sort_keys=True), now),
            )
        return self.get(position_id)

    def reconcile_entry(self, position_id: str, *, cumulative_filled: str,
                        average_price: str, observed_ts: int) -> dict[str, Any]:
        row = self.get(position_id)
        if not row:
            raise ValueError("position not found")
        filled, previous = Decimal(cumulative_filled), Decimal(row["entry_filled"])
        target, price = Decimal(row["target_quantity"]), Decimal(average_price)
        if filled < previous or filled > target or not Decimal(0) < price < Decimal(1):
            raise ValueError("invalid cumulative entry fill")
        status = "ENTRY_OPEN" if filled == 0 else ("OPEN" if filled == target else "PARTIALLY_FILLED")
        first_fill = row["first_fill_ts"] or (observed_ts if filled > 0 else None)
        with self._connect() as db:
            db.execute(
                "UPDATE positions SET entry_filled=?,average_entry_price=?,first_fill_ts=?,"
                "status=?,updated_at=? WHERE position_id=?",
                (str(filled), str(price), first_fill, status,
                 datetime.now(timezone.utc).isoformat(), position_id),
            )
        return self.get(position_id)

    def reserve_exit(self, position_id: str, *, reason: str, exit_order_id: str) -> dict[str, Any]:
        row = self.get(position_id)
        if not row or Decimal(row["entry_filled"]) <= Decimal(row["exit_filled"]):
            raise ValueError("position has no quantity available to exit")
        if row["exit_order_id"]:
            return row
        with self._connect() as db:
            db.execute(
                "UPDATE positions SET exit_reason=?,exit_order_id=?,status='EXIT_OPEN',"
                "updated_at=? WHERE position_id=? AND exit_order_id IS NULL",
                (reason, exit_order_id, datetime.now(timezone.utc).isoformat(), position_id),
            )
        return self.get(position_id)

    def reconcile_exit(self, position_id: str, *, cumulative_filled: str) -> dict[str, Any]:
        row = self.get(position_id)
        if not row or not row["exit_order_id"]:
            raise ValueError("position has no reserved exit")
        filled, previous = Decimal(cumulative_filled), Decimal(row["exit_filled"])
        entry_filled = Decimal(row["entry_filled"])
        if filled < previous or filled > entry_filled:
            raise ValueError("invalid cumulative exit fill")
        status = "CLOSED" if filled == entry_filled else "EXIT_PARTIALLY_FILLED"
        with self._connect() as db:
            db.execute(
                "UPDATE positions SET exit_filled=?,status=?,updated_at=? WHERE position_id=?",
                (str(filled), status, datetime.now(timezone.utc).isoformat(), position_id),
            )
        return self.get(position_id)

    def recoverable(self) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM positions WHERE status != 'CLOSED' ORDER BY updated_at"
            ).fetchall()
        return [dict(row) for row in rows]
