import tempfile
from decimal import Decimal
from pathlib import Path

import pytest

from rwoo.position_monitor import ExitPolicy, PositionStore, exit_trigger


POLICY = ExitPolicy("25", "15", 3600, 150, "oracle_invalidated")


def _open(store):
    store.create(position_id="p1", token_id="t1", entry_order_id="buy1",
                 target_quantity="10", policy=POLICY)
    return store.reconcile_entry("p1", cumulative_filled="4",
                                 average_price="0.42", observed_ts=1000)


def test_trigger_priority_and_executable_bid():
    with tempfile.TemporaryDirectory() as tmp:
        row = _open(PositionStore(Path(tmp) / "positions.sqlite"))
        assert exit_trigger(row, executable_bid=Decimal("0.30"), invalidated=True,
                            now_ts=5000, kill_switch=True) == "KILL_SWITCH"
        assert exit_trigger(row, executable_bid=Decimal("0.30"), invalidated=True,
                            now_ts=5000) == "INVALIDATION"
        assert exit_trigger(row, executable_bid=Decimal("0.357"), invalidated=False,
                            now_ts=1001) == "STOP_LOSS"
        assert exit_trigger(row, executable_bid=Decimal("0.50"), invalidated=False,
                            now_ts=4600) == "TIME_EXIT"
        assert exit_trigger(row, executable_bid=Decimal("0.525"), invalidated=False,
                            now_ts=1001) == "TAKE_PROFIT"


def test_partial_fill_is_protected_and_exit_is_idempotent():
    with tempfile.TemporaryDirectory() as tmp:
        store = PositionStore(Path(tmp) / "positions.sqlite")
        row = _open(store)
        assert row["status"] == "PARTIALLY_FILLED"
        first = store.reserve_exit("p1", reason="STOP_LOSS", exit_order_id="sell1")
        second = store.reserve_exit("p1", reason="TAKE_PROFIT", exit_order_id="sell2")
        assert first["exit_order_id"] == second["exit_order_id"] == "sell1"
        assert store.reconcile_exit("p1", cumulative_filled="2")["status"] == "EXIT_PARTIALLY_FILLED"
        assert store.reconcile_exit("p1", cumulative_filled="4")["status"] == "CLOSED"


def test_restart_recovers_without_duplicate_exit():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "positions.sqlite"
        first = PositionStore(path)
        _open(first)
        first.reserve_exit("p1", reason="TIME_EXIT", exit_order_id="sell1")
        restarted = PositionStore(path)
        rows = restarted.recoverable()
        assert len(rows) == 1
        assert rows[0]["exit_order_id"] == "sell1"
        assert restarted.reserve_exit("p1", reason="STOP_LOSS",
                                      exit_order_id="sell2")["exit_order_id"] == "sell1"


def test_cumulative_fills_cannot_move_backward_or_oversell():
    with tempfile.TemporaryDirectory() as tmp:
        store = PositionStore(Path(tmp) / "positions.sqlite")
        _open(store)
        with pytest.raises(ValueError):
            store.reconcile_entry("p1", cumulative_filled="3", average_price="0.42", observed_ts=1001)
        store.reserve_exit("p1", reason="STOP_LOSS", exit_order_id="sell1")
        with pytest.raises(ValueError):
            store.reconcile_exit("p1", cumulative_filled="5")
