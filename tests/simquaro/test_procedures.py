"""Procedure tests advance registered timers and observe completed actions."""

import asyncio
from datetime import datetime, timezone
import unittest

from simquaro.config import ReceiverConfig
from simquaro.faults import FaultController
from simquaro.protocol import NumericToken as N, Request
from simquaro.receivers.fictitious import FictitiousReceiverSimulator
from tests.simquaro.support.clock import VirtualClock
from tests.simquaro.test_receiver import turns


class ProcedureTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.clock = VirtualClock()
        self.faults = FaultController()
        self.model = FictitiousReceiverSimulator(ReceiverConfig(), faults=self.faults, clock=self.clock)
        self.addAsyncCleanup(self.model.close)

    async def request(self, verb, **fields):
        return (await self.model.handle(Request(verb, 1, {}, fields), session_id="a")).response

    async def tick(self, seconds):
        await turns()
        self.clock.advance(seconds)
        await turns()

    async def named(self, name="calibrate"):
        return (await self.request("status", name=name)).fields

    async def complete_calibration(self):
        await self.tick(.1)
        await self.tick(.9)
        await self.tick(8)
        await self.tick(.1)
        await self.tick(.9)

    async def test_calibration_registers_busy_and_restores_before_success(self):
        self.assertEqual((await self.request("run", name="calibrate")).verb, "accepted")
        first = await self.named()
        self.assertEqual(first["state"], "running")
        self.assertNotIn("progress", first)
        self.assertEqual((await self.request("run", name="calibrate")).fields["code"], "BUSY")
        self.assertEqual((await self.request("run", name="scan", start=N("5"), stop=N("6"), unit="GHz", dwell_ms=N("1"))).fields["code"], "BUSY")
        self.assertEqual((await self.request("get", name="frequency")).fields["reason"], "CALIBRATING")
        await self.tick(.1)
        self.assertEqual(self.model.snapshot()["actual"]["frequency"], "6")
        await self.tick(.9)
        self.assertEqual(self.model.snapshot()["actual"]["phase"], "reference_measurement")
        await self.tick(8)
        self.assertEqual((await self.request("cancel", name="calibrate")).fields["code"], "NOT_CANCELLABLE")
        self.assertIsNone(self.model.snapshot()["actual"]["stop_deadline"])
        await self.tick(.1)
        await self.tick(.9)
        self.assertEqual((await self.named())["state"], "succeeded")
        self.assertEqual(self.model.snapshot()["actual"]["frequency"], "5")
        self.assertTrue(self.model.snapshot()["actual"]["procedures"]["calibrate"]["reference_verified"])
        self.assertTrue(self.model.snapshot()["actual"]["procedures"]["calibrate"]["restoration_verified"])
        self.assertTrue((await self.request("status")).fields["calibrated"])
        self.assertEqual((await self.named())["started_at"], first["started_at"])
        # Same effective frequency retains calibration; changed effective value invalidates it.
        for value, calibrated in [("5.0000004", True), ("5.0000005", False)]:
            task = asyncio.create_task(self.request("set", name="frequency", value=N(value), unit="GHz"))
            await self.tick(.1)
            self.assertEqual((await task).verb, "ok")
            self.assertEqual((await self.request("status")).fields["calibrated"], calibrated)
        self.assertEqual((await self.named())["state"], "succeeded")

    async def test_reference_phase_hook_occurs_once_after_acceptance_not_polling(self):
        self.faults.schedule("calibration_reference_unavailable", when="calibrate_reference_measurement", times=2)
        await self.request("run", name="calibrate")
        self.assertFalse(self.faults.is_active("calibration_reference_unavailable"))
        await self.tick(.1)
        await self.tick(.9)
        self.assertEqual((await self.named())["state"], "failed")
        self.assertEqual((await self.named())["error_code"], "CALIBRATION_REFERENCE_UNAVAILABLE")
        self.assertEqual((await self.request("status")).fields["health"], "ok")
        for _ in range(3):
            await self.named()
        self.assertEqual(self.faults.snapshot()["rules"][0]["remaining"], 1)
        self.faults.clear("calibration_reference_unavailable")
        self.assertEqual((await self.named())["state"], "failed")

    async def test_restoration_failure_is_failed_not_calibrated(self):
        await self.request("run", name="calibrate")
        await self.tick(.1)
        await self.tick(.9)
        self.faults.activate("frequency_lock_failure")
        await self.tick(8)
        await self.tick(1)
        self.assertEqual((await self.named())["state"], "failed")
        self.assertEqual((await self.named())["error_code"], "FREQUENCY_LOCK_FAILED")
        self.assertFalse((await self.request("status")).fields["calibrated"])
        self.assertFalse(self.model.snapshot()["actual"]["frequency_verified"])

    async def test_ten_exact_points_both_directions_and_hold_before_counting(self):
        asc = ["5", "5.022222", "5.044444", "5.066667", "5.088889", "5.111111", "5.133333", "5.155556", "5.177778", "5.2"]
        for start, stop, expected in [("5", "5.2", asc), ("5.2", "5", list(reversed(asc)))]:
            self.assertEqual((await self.request("run", name="scan", start=N(start), stop=N(stop), unit="GHz", dwell_ms=N("1"))).verb, "accepted")
            await turns()
            self.assertEqual(self.model.snapshot()["actual"]["scan_targets"], expected)
            for index, target in enumerate(expected):
                self.assertEqual((await self.request("get", name="frequency")).fields["reason"], "TUNING")
                await self.tick(.1)
                self.assertEqual(str((await self.request("get", name="frequency")).fields["value"]), target)
                self.assertEqual(str((await self.named("scan"))["points_completed"]), str(index))
                await self.tick(.001)
            self.assertEqual((await self.named("scan"))["state"], "succeeded")
            self.assertEqual(str((await self.named("scan"))["points_completed"]), "10")
            self.assertEqual(self.model.snapshot()["actual"]["frequency"], stop)

    async def test_scan_validation_has_no_effect_and_retains_previous_outcome(self):
        cases = [({"start": N("5"), "stop": N("5.000001")}, "INVALID_PARAMETER"),
                 ({"start": N("0.9999999"), "stop": N("6")}, "OUT_OF_RANGE"),
                 ({"dwell_ms": N("1.0")}, "INVALID_TYPE"),
                 ({"dwell_ms": N("1e0")}, "INVALID_TYPE"),
                 ({"dwell_ms": N("+1")}, "INVALID_TYPE"),
                 ({"dwell_ms": N("-1")}, "INVALID_TYPE"),
                 ({"dwell_ms": N("0")}, "OUT_OF_RANGE"),
                 ({"dwell_ms": N("1001")}, "OUT_OF_RANGE"),
                 ({"step": N("1")}, "UNKNOWN_PARAMETER")]
        for changes, code in cases:
            fields = {"name": "scan", "start": N("5"), "stop": N("6"), "unit": "GHz", "dwell_ms": N("1")}
            fields.update(changes)
            response = await self.request("run", **fields)
            self.assertEqual(response.fields["code"], code)
            self.assertEqual((await self.named("scan"))["state"], "unknown")
        self.assertEqual(self.model.snapshot()["actual"]["frequency"], "5")

    async def assert_scan_rejects_lost_hold(self, completed, *, poll_during_fault):
        clock = VirtualClock()
        faults = FaultController()
        model = FictitiousReceiverSimulator(ReceiverConfig(), faults=faults, clock=clock)
        self.addAsyncCleanup(model.close)
        await model.handle(Request("run", 1, {}, {"name": "scan", "start": N("5"),
                           "stop": N("6"), "unit": "GHz", "dwell_ms": N("1000")}), session_id="a")

        async def tick(seconds):
            await turns()
            clock.advance(seconds)
            await turns()

        for _ in range(completed):
            await tick(.1)
            await tick(1)
        await tick(.1)
        faults.activate("synthesizer_failure")
        if poll_during_fault:
            await model.handle(Request("status", 2, {}, {}), session_id="a")
        await tick(1)
        # Inspect retained procedure status first: no request/snapshot diagnostic
        # call may be needed to make the procedure detect its own hardware loss.
        result = model._procedures.status("scan")
        self.assertEqual(result["state"], "failed")
        self.assertEqual(result["error_code"], "FREQUENCY_LOCK_FAILED")
        self.assertEqual(str(result["points_completed"]), str(completed))
        snapshot = model.snapshot()
        self.assertFalse(snapshot["actual"]["frequency_verified"])
        self.assertFalse(snapshot["actual"]["procedure_active"])
        self.assertEqual(snapshot["reported"]["general"]["health"], "fault")

    async def test_final_scan_hold_requires_surviving_verified_frequency(self):
        for poll in (False, True):
            with self.subTest(poll_during_fault=poll):
                await self.assert_scan_rejects_lost_hold(9, poll_during_fault=poll)

    async def test_earlier_scan_hold_failure_is_not_credited_or_skipped(self):
        for poll in (False, True):
            with self.subTest(poll_during_fault=poll):
                await self.assert_scan_rejects_lost_hold(1, poll_during_fault=poll)

    async def test_repeated_cancel_preserves_deadline_and_late_verified_stop_recovers(self):
        self.faults.activate("procedure_stall")
        self.faults.activate("stop_unconfirmed")
        await self.request("run", name="calibrate")
        await self.request("cancel", name="calibrate")
        deadline = self.model.snapshot()["actual"]["stop_deadline"]
        await self.tick(4)
        await self.request("cancel", name="calibrate")
        self.assertEqual(self.model.snapshot()["actual"]["stop_deadline"], deadline)
        await self.tick(1)
        self.assertEqual((await self.named())["state"], "cancelling")
        self.assertNotIn("finished_at", await self.named())
        self.assertIn("STOP_TIMEOUT", (await self.request("status")).fields["fault_codes"])
        self.assertEqual((await self.request("status")).fields["activity"], "calibrating")
        self.assertEqual((await self.request("set", name="frequency", value=N("6"), unit="GHz")).fields["code"], "BUSY")
        self.faults.clear("stop_unconfirmed")
        await self.tick(.05)
        await self.tick(.1)
        self.assertEqual((await self.named())["state"], "cancelled")
        self.assertEqual((await self.request("status")).fields["activity"], "idle")
        self.assertNotIn("STOP_TIMEOUT", (await self.request("status")).fields["fault_codes"])
        self.assertTrue(self.model.snapshot()["incidents"])

    async def test_execution_deadlines_are_independent_of_utc_and_add_stop_budget(self):
        for name, limit, error in [("calibrate", 30, "CALIBRATION_TIMEOUT"), ("scan", 20, "SCAN_TIMEOUT")]:
            self.faults.activate("procedure_stall")
            self.faults.activate("stop_unconfirmed")
            fields = {"name": name}
            if name == "scan":
                fields.update(start=N("5"), stop=N("6"), unit="GHz", dwell_ms=N("1"))
            await self.request("run", **fields)
            self.clock.set_utc(datetime(2000, 1, 1, tzinfo=timezone.utc))
            self.faults.activate("clock_untrusted")
            await self.tick(limit - .001)
            self.assertEqual((await self.named(name))["state"], "running")
            await self.tick(.001)
            self.assertEqual((await self.named(name))["state"], "cancelling")
            self.assertNotIn("STOP_TIMEOUT", (await self.request("status")).fields["fault_codes"])
            await self.tick(5)
            self.assertIn("STOP_TIMEOUT", (await self.request("status")).fields["fault_codes"])
            self.faults.clear("stop_unconfirmed")
            await self.tick(.05)
            await self.tick(.1)
            result = await self.named(name)
            self.assertEqual(result["state"], "failed")
            self.assertEqual(result["error_code"], error)

    async def test_deadline_can_stop_non_cancellable_stalled_finalization(self):
        await self.request("run", name="calibrate")
        await self.tick(.1)
        await self.tick(.9)
        await self.tick(8)
        self.faults.activate("procedure_stall")
        await self.tick(.1)
        await self.tick(20.9)
        self.assertEqual((await self.named())["state"], "cancelling")
        await self.tick(.1)
        self.assertEqual((await self.named())["error_code"], "CALIBRATION_TIMEOUT")

    async def test_internal_tuning_does_not_consume_external_set_rule(self):
        self.faults.schedule("drop_response", when="frequency_set_verified", times=2)
        await self.request("run", name="calibrate")
        await self.complete_calibration()
        self.assertEqual((await self.named())["state"], "succeeded")
        self.assertEqual(self.faults.snapshot()["rules"][0]["remaining"], 2)

    async def test_tuning_failure_stops_scan_without_skipping_point(self):
        await self.request("run", name="scan", start=N("5"), stop=N("6"), unit="GHz", dwell_ms=N("1"))
        await self.tick(.1)
        self.faults.activate("frequency_lock_failure")
        await self.tick(.001)
        await self.tick(1)
        result = await self.named("scan")
        self.assertEqual(result["state"], "failed")
        self.assertEqual(str(result["points_completed"]), "1")
        self.assertEqual(result["error_code"], "FREQUENCY_LOCK_FAILED")
        self.assertFalse(self.model.snapshot()["actual"]["frequency_verified"])

    async def test_stop_deadline_is_enforced_even_when_confirmation_action_is_delayed(self):
        self.faults.activate("procedure_stall")
        await self.request("run", name="calibrate")
        await self.request("cancel", name="calibrate")
        await turns()
        self.faults.activate("stop_unconfirmed")
        await self.tick(5)
        self.assertIn("STOP_TIMEOUT", (await self.request("status")).fields["fault_codes"])
        self.assertEqual((await self.named())["state"], "cancelling")

    async def test_natural_completion_after_execution_timeout_remains_failed(self):
        await self.request("run", name="calibrate")
        await self.tick(.1)
        await self.tick(.9)
        await self.tick(8)
        await self.tick(.1)
        self.faults.activate("procedure_stall")
        self.faults.activate("stop_unconfirmed")
        await self.tick(20.9)
        self.assertEqual((await self.named())["state"], "cancelling")
        self.faults.clear("procedure_stall")
        await self.tick(.05)
        self.assertEqual((await self.named())["state"], "failed")
        self.assertEqual((await self.named())["error_code"], "CALIBRATION_TIMEOUT")
        self.assertFalse((await self.request("status")).fields["calibrated"])

    async def test_untrusted_completion_omits_only_new_utc_timestamp(self):
        await self.request("run", name="calibrate")
        before = await self.named()
        self.faults.activate("clock_untrusted")
        await self.complete_calibration()
        result = await self.named()
        self.assertEqual(result["state"], "succeeded")
        self.assertEqual(result["started_at"], before["started_at"])
        self.assertNotIn("finished_at", result)
        self.faults.clear("clock_untrusted")
        self.assertNotIn("finished_at", await self.named())

    async def test_scan_cancel_confirmed_during_hold_retains_verified_value_and_outcome(self):
        await self.request("run", name="scan", start=N("5"), stop=N("6"), unit="GHz", dwell_ms=N("1000"))
        await self.tick(.1)
        self.assertEqual((await self.request("cancel", name="scan")).verb, "accepted")
        self.assertEqual((await self.named("scan"))["state"], "cancelling")
        await self.tick(.1)
        result = await self.named("scan")
        self.assertEqual(result["state"], "cancelled")
        self.assertEqual(str(result["points_completed"]), "0")
        self.assertEqual(str((await self.request("get", name="frequency")).fields["value"]), "5")
        rejected = await self.request("run", name="scan", start=N("5"), stop=N("5.000008"), unit="GHz", dwell_ms=N("1000"))
        self.assertEqual(rejected.fields["code"], "INVALID_PARAMETER")
        self.assertEqual(await self.named("scan"), result)

    async def test_minimum_span_has_ten_distinct_targets(self):
        response = await self.request("run", name="scan", start=N("5.0000001"), stop=N("5.0000094"), unit="GHz", dwell_ms=N("1000"))
        self.assertEqual(response.verb, "accepted")
        self.assertEqual(self.model.snapshot()["actual"]["scan_targets"],
                         ["5", "5.000001", "5.000002", "5.000003", "5.000004", "5.000005", "5.000006", "5.000007", "5.000008", "5.000009"])

    async def test_cancel_completion_race_records_actual_success_and_late_cancel_rejects(self):
        await self.request("run", name="scan", start=N("5"), stop=N("6"), unit="GHz", dwell_ms=N("1"))
        for _ in range(9):
            await self.tick(.1)
            await self.tick(.001)
        await self.tick(.1)
        self.assertEqual((await self.request("cancel", name="scan")).verb, "accepted")
        await self.tick(.001)
        self.assertEqual((await self.named("scan"))["state"], "succeeded")
        self.assertEqual((await self.request("cancel", name="scan")).fields["code"], "NOT_RUNNING")

    async def test_close_and_reboot_do_not_fabricate_cancelled_outcomes(self):
        await self.request("run", name="calibrate")
        await turns()
        await self.model.close()
        self.assertEqual(self.model.snapshot()["reported"]["procedures"]["calibrate"]["state"], "running")
        self.assertTrue(self.model.snapshot()["actual"]["procedure_active"])
        await self.model.reboot()
        self.assertEqual((await self.named())["state"], "unknown")
        self.assertFalse(self.model.snapshot()["actual"]["procedure_active"])


if __name__ == "__main__":
    unittest.main()
