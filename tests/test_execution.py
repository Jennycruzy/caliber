from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rwoo.execution import ExecutionCoordinator, ExecutionError, ExecutionStore, VenueResult


def order(**changes):
    payload = {
        "venue": "polymarket", "market_id": "market-1", "token_id": "token-yes",
        "side": "YES", "price": "0.333333", "quantity": "3",
        "time_in_force": "GTC", "event_group_id": "event-1",
        "decision_receipt_hash": "receipt-1",
    }
    payload.update(changes)
    return payload


class FakeAdapter:
    def __init__(self, result=None, error=None):
        self.result = result or VenueResult("OPEN", "venue-1")
        self.error = error
        self.submissions = 0

    def submit(self, intent):
        self.submissions += 1
        if self.error:
            raise self.error
        return self.result

    def cancel(self, intent):
        return VenueResult("CANCELLED", intent.get("venue_order_id"))

    def reconcile(self, intent):
        return self.result


class ExecutionCoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "execution.sqlite3"

    def tearDown(self):
        self.tmp.cleanup()

    def coordinator(self, **kwargs):
        return ExecutionCoordinator(ExecutionStore(self.path), **kwargs)

    def test_exact_arithmetic_and_durable_restart(self):
        coordinator = self.coordinator()
        intent, replay = coordinator.prepare(order(), "key-1")
        self.assertFalse(replay)
        self.assertEqual(intent["notional"], "0.999999")
        restarted = self.coordinator().store.get(intent["intent_id"])
        self.assertEqual(restarted["state"], "PREPARED")

    def test_float_input_is_rejected(self):
        with self.assertRaisesRegex(ExecutionError, "decimal string"):
            self.coordinator().prepare(order(price=0.4), "key-float")

    def test_idempotency_replays_and_conflicts(self):
        coordinator = self.coordinator()
        first, replay = coordinator.prepare(order(), "same-key")
        second, replay = coordinator.prepare(order(), "same-key")
        self.assertTrue(replay)
        self.assertEqual(first["intent_id"], second["intent_id"])
        with self.assertRaisesRegex(ExecutionError, "bound"):
            coordinator.prepare(order(quantity="4"), "same-key")

    def test_disabled_mode_never_submits(self):
        coordinator = self.coordinator()
        intent, _ = coordinator.prepare(order(), "key-disabled")
        with self.assertRaisesRegex(ExecutionError, "locked"):
            coordinator.submit(intent["intent_id"], "approval")
        self.assertEqual(coordinator.store.get(intent["intent_id"])["state"], "PREPARED")

    def test_ambiguous_submit_is_unknown_not_rejected(self):
        adapter = FakeAdapter(error=TimeoutError())
        coordinator = self.coordinator(mode="live", adapter=adapter)
        intent, _ = coordinator.prepare(order(), "key-timeout")
        result = coordinator.submit(intent["intent_id"], "approval-1")
        self.assertEqual(result["state"], "UNKNOWN")
        self.assertEqual(adapter.submissions, 1)
        with self.assertRaisesRegex(ExecutionError, "cannot transition"):
            coordinator.submit(intent["intent_id"], "approval-1")
        self.assertEqual(adapter.submissions, 1)

    def test_prepared_intent_can_be_cancelled_without_adapter(self):
        coordinator = self.coordinator()
        intent, _ = coordinator.prepare(order(), "key-cancel")
        result = coordinator.cancel(intent["intent_id"])
        self.assertEqual(result["state"], "CANCELLED")

    def test_limit_is_enforced_exactly(self):
        coordinator = self.coordinator(max_order_usd="1.00")
        coordinator.prepare(order(price="0.50", quantity="2"), "at-limit")
        with self.assertRaisesRegex(ExecutionError, "limit"):
            coordinator.prepare(order(price="0.500001", quantity="2"), "over-limit")

    def test_buyer_signal_refs_are_scoped_and_kill_switch_blocks_prepare(self):
        coordinator = self.coordinator()
        buyer_a = coordinator.store.buyer("0x" + "11" * 20)
        buyer_b = coordinator.store.buyer("0x" + "22" * 20)
        reference = coordinator.store.create_signal_ref(
            buyer_a["buyer_id"], {"market_id": "market-1"},
            "2099-01-01T00:00:00+00:00",
        )
        self.assertIsNotNone(coordinator.store.signal_ref(
            reference["signal_id"], buyer_a["buyer_id"]
        ))
        self.assertIsNone(coordinator.store.signal_ref(
            reference["signal_id"], buyer_b["buyer_id"]
        ))
        coordinator.store.set_kill_switch(
            buyer_a["buyer_id"], active=True, reason="operator emergency"
        )
        with self.assertRaisesRegex(ExecutionError, "emergency stop"):
            coordinator.prepare(order(
                buyer_id=buyer_a["buyer_id"],
                signal_id=reference["signal_id"],
                signal_expires_at=reference["expires_at"],
            ), "buyer-stopped")

    def test_control_nonce_is_one_shot(self):
        coordinator = self.coordinator()
        buyer = coordinator.store.buyer("0x" + "11" * 20)
        coordinator.store.consume_control_nonce(buyer["buyer_id"], "n" * 16)
        with self.assertRaisesRegex(ExecutionError, "already used"):
            coordinator.store.consume_control_nonce(buyer["buyer_id"], "n" * 16)

    def test_buyer_signed_submission_requires_explicit_approval(self):
        coordinator = self.coordinator()
        buyer = coordinator.store.buyer("0x" + "11" * 20)
        intent, _ = coordinator.prepare(
            order(buyer_id=buyer["buyer_id"]), "buyer-approval"
        )
        with self.assertRaisesRegex(ExecutionError, "explicit buyer approval"):
            coordinator.submit_signed(intent["intent_id"], "a" * 64, lambda _: None)
        self.assertEqual(
            coordinator.store.get(intent["intent_id"])["state"], "PREPARED"
        )


EXIT_POLICY = {
    "take_profit_pct": "25",
    "stop_loss_pct": "15",
    "max_hold_seconds": 3600,
    "max_exit_slippage_bps": 150,
    "invalidation_rule": "oracle_invalidated",
}


class PositionBindingTests(unittest.TestCase):
    """Prove that confirmed fills flow into the PositionStore."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.exec_path = self.root / "execution.sqlite3"
        self.pos_path = self.root / "positions.sqlite"

    def tearDown(self):
        self.tmp.cleanup()

    def _coordinator(self, **kwargs):
        from rwoo.position_monitor import PositionStore

        return ExecutionCoordinator(
            ExecutionStore(self.exec_path),
            position_store=PositionStore(self.pos_path),
            **kwargs,
        )

    def test_buy_fill_creates_and_reconciles_position(self):
        adapter = FakeAdapter(result=VenueResult("FILLED", "venue-buy-1",
                                                  filled_quantity="3",
                                                  average_fill_price="0.333"))
        coord = self._coordinator(mode="live", adapter=adapter)
        intent, _ = coord.prepare(order(exit_policy=EXIT_POLICY), "key-buy")
        self.assertIsNotNone(intent.get("position_id"))
        self.assertEqual(intent["order_direction"], "BUY")

        # Position exists in PositionStore before submission (ENTRY_OPEN)
        pos = coord.position_store.get(intent["position_id"])
        self.assertIsNotNone(pos)
        self.assertEqual(pos["status"], "ENTRY_OPEN")
        self.assertEqual(pos["entry_filled"], "0")

        # Submit → fills land → position reconciled
        result = coord.submit(intent["intent_id"], "approval-1")
        self.assertEqual(result["state"], "FILLED")
        pos = coord.position_store.get(intent["position_id"])
        self.assertEqual(pos["entry_filled"], "3")
        self.assertEqual(pos["average_entry_price"], "0.333")
        self.assertEqual(pos["status"], "OPEN")

    def test_partial_buy_fill_is_protected_immediately(self):
        adapter = FakeAdapter(result=VenueResult("PARTIALLY_FILLED", "venue-pf-1",
                                                  filled_quantity="1",
                                                  average_fill_price="0.333"))
        coord = self._coordinator(mode="live", adapter=adapter)
        intent, _ = coord.prepare(order(exit_policy=EXIT_POLICY), "key-partial")
        result = coord.submit(intent["intent_id"], "approval-1")
        self.assertEqual(result["state"], "PARTIALLY_FILLED")

        pos = coord.position_store.get(intent["position_id"])
        self.assertEqual(pos["entry_filled"], "1")
        self.assertEqual(pos["status"], "PARTIALLY_FILLED")

    def test_sell_fill_reconciles_exit(self):
        from rwoo.position_monitor import PositionStore

        pos_store = PositionStore(self.pos_path)
        # Set up a filled BUY position first
        buy_adapter = FakeAdapter(result=VenueResult("FILLED", "venue-buy-2",
                                                      filled_quantity="3",
                                                      average_fill_price="0.333"))
        coord = ExecutionCoordinator(
            ExecutionStore(self.exec_path),
            mode="live", adapter=buy_adapter, position_store=pos_store,
        )
        buy_intent, _ = coord.prepare(order(exit_policy=EXIT_POLICY), "key-buy-2")
        coord.submit(buy_intent["intent_id"], "approval-buy")
        position_id = buy_intent["position_id"]
        pos = pos_store.get(position_id)
        self.assertEqual(pos["entry_filled"], "3")

        # Reserve exit on the position
        pos_store.reserve_exit(position_id, reason="TAKE_PROFIT", exit_order_id="sell-intent")

        # Now prepare and submit a SELL intent linked to this position
        sell_adapter = FakeAdapter(result=VenueResult("FILLED", "venue-sell-2",
                                                       filled_quantity="3",
                                                       average_fill_price="0.40"))
        coord2 = ExecutionCoordinator(
            ExecutionStore(self.exec_path),
            mode="live", adapter=sell_adapter, position_store=pos_store,
        )
        sell_intent, _ = coord2.prepare(
            order(position_id=position_id, order_direction="SELL"),
            "key-sell-2",
        )
        self.assertEqual(sell_intent["order_direction"], "SELL")
        self.assertEqual(sell_intent["position_id"], position_id)
        result = coord2.submit(sell_intent["intent_id"], "approval-sell")
        self.assertEqual(result["state"], "FILLED")

        pos = pos_store.get(position_id)
        self.assertEqual(pos["exit_filled"], "3")
        self.assertEqual(pos["status"], "CLOSED")

    def test_restart_recovery_finds_open_positions(self):
        adapter = FakeAdapter(result=VenueResult("FILLED", "venue-buy-3",
                                                  filled_quantity="3",
                                                  average_fill_price="0.333"))
        coord = self._coordinator(mode="live", adapter=adapter)
        intent, _ = coord.prepare(order(exit_policy=EXIT_POLICY), "key-restart")
        coord.submit(intent["intent_id"], "approval-1")

        # Simulate restart — fresh PositionStore on the same db
        from rwoo.position_monitor import PositionStore

        restarted = PositionStore(self.pos_path)
        rows = restarted.recoverable()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["position_id"], intent["position_id"])
        self.assertEqual(rows[0]["entry_filled"], "3")
        self.assertEqual(rows[0]["status"], "OPEN")

    def test_no_position_store_is_backwards_compatible(self):
        """Coordinator without position_store works exactly as before."""
        adapter = FakeAdapter(result=VenueResult("FILLED", "venue-1",
                                                  filled_quantity="3",
                                                  average_fill_price="0.333"))
        coord = ExecutionCoordinator(
            ExecutionStore(self.exec_path),
            mode="live", adapter=adapter,
        )
        intent, _ = coord.prepare(order(exit_policy=EXIT_POLICY), "key-compat")
        self.assertIsNone(intent.get("position_id"))
        result = coord.submit(intent["intent_id"], "approval-1")
        self.assertEqual(result["state"], "FILLED")

    def test_idempotent_replay_does_not_duplicate_position(self):
        coord = self._coordinator()
        payload = order(exit_policy=EXIT_POLICY)
        first, replay1 = coord.prepare(payload, "key-idem")
        self.assertFalse(replay1)
        second, replay2 = coord.prepare(payload, "key-idem")
        self.assertTrue(replay2)
        self.assertEqual(first["intent_id"], second["intent_id"])
        # Only one position was created
        from rwoo.position_monitor import PositionStore

        restarted = PositionStore(self.pos_path)
        rows = restarted.recoverable()
        self.assertEqual(len(rows), 1)


if __name__ == "__main__":
    unittest.main()
