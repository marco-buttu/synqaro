"""Receiver requests use the real model, fault controller and virtual clock."""

import asyncio
from dataclasses import replace
import json
import unittest

from simquaro.models.fictitious_receiver.config import ReceiverConfig
from simquaro.models.fictitious_receiver.faults import receiver_faults as FaultController
from synqaro_protocol.codec import NumericToken as N, Request, encode_response, parse_request
from simquaro.models.fictitious_receiver.model import FictitiousReceiverSimulator
from tests.simquaro.support.clock import VirtualClock


async def turns():
    for _ in range(12):
        await asyncio.sleep(0)


class ReceiverTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_descriptor_unknown_cold_history_and_known_fresh_observation(self):
        response = await self.request("get", name="configuration")
        self.assertEqual(response.verb, "ok")
        self.assertEqual(response.fields["readonly_properties"], ["configuration"])
        self.assertEqual(response.fields["supported_procedures"], ["calibrate", "scan"])
        self.assertEqual(str(response.fields["frequency_resolution"]), "0.000001")
        self.assertEqual(str(response.fields["calibrate_timeout_ms"]), "30000")
        self.assertEqual(response.fields["calibrate_cancellation"], "except_finalization")
        self.assertLessEqual(len(encode_response(response)), 4096)
        self.assertEqual((await self.request("status", name="calibrate")).fields,
                         {"name": "calibrate", "state": "unknown"})
        self.model._procedures.attempts["calibrate"] = replace(
            self.model._procedures.attempts["calibrate"], state="never_started")
        self.assertEqual((await self.request("status", name="calibrate")).fields,
                         {"name": "calibrate", "state": "never_started"})

    async def test_validation_catalog_and_bounded_unknown_context(self):
        cases = [("get", {}, "MISSING_PARAMETER"),
                 ("get", {"name": "missing"}, "UNKNOWN_PROPERTY"),
                 ("set", {"name": "configuration"}, "READ_ONLY_PROPERTY"),
                 ("get", {"name": "frequency", "unit": "MHz"}, "UNKNOWN_PARAMETER"),
                 ("run", {"name": "missing"}, "UNKNOWN_PROCEDURE"),
                 ("status", {"name": "reboot"}, "UNKNOWN_PROCEDURE"),
                 ("cancel", {"name": "scan"}, "NOT_RUNNING"),
                 ("reboot", {"name": "x"}, "UNKNOWN_PARAMETER"),
                 ("set", {"name": "frequency", "value": "5", "unit": "GHz"}, "INVALID_TYPE"),
                 ("set", {"name": "frequency", "value": N("10.0000001"), "unit": "GHz"}, "OUT_OF_RANGE"),
                 ("set", {"name": "frequency", "value": N("5"), "unit": "MHz"}, "UNSUPPORTED_UNIT")]
        for verb, fields, code in cases:
            with self.subTest(verb=verb, fields=fields):
                response = await self.request(verb, **fields)
                self.assertEqual(response.fields["code"], code)
        for frame in [b'#get <id=1>: name="' + b'x' * 4000 + b'"\n',
                      b'#' + b'x' * 4000 + b' <id=1>\n',
                      b'#get <id=1, ' + b'x' * 3900 + b'=true>: name=frequency\n']:
            response = (await self.model.handle(parse_request(frame), session_id="a")).response
            self.assertEqual(response.verb, "error")
            self.assertLessEqual(len(encode_response(response)), 4096)
        self.assertEqual(self.model.snapshot()["actual"]["frequency"], "5")

    async def test_external_set_commits_before_hook_and_does_not_emit_response_ready(self):
        self.faults.schedule("drop_response", when="frequency_set_verified")
        self.faults.schedule("clock_untrusted", when="response_ready")
        task = asyncio.create_task(self.model.handle(Request("set", 7, {}, {
            "name": "frequency", "value": N("5.1234565"), "unit": "GHz"}), session_id="b"))
        await turns()
        snap = self.model.snapshot()
        self.assertEqual(snap["actual"]["requested_target"], "5.123457")
        self.assertFalse(snap["actual"]["frequency_verified"])
        self.assertEqual((await self.request("get", name="frequency")).fields["reason"], "TUNING")
        self.assertEqual((await self.request("set", name="frequency", value=N("6"), unit="GHz")).fields["code"], "BUSY")
        await self.tick(.1)
        reply = await task
        self.assertEqual(reply.response.verb, "ok")
        self.assertEqual(str(reply.response.fields["value"]), "5.123457")
        self.assertEqual([effect.name for effect in reply.delivery_effects], ["drop_response"])
        self.assertEqual(self.model.snapshot()["actual"]["frequency"], "5.123457")
        self.assertFalse(self.faults.is_active("clock_untrusted"))

    async def test_failed_lock_never_reports_requested_value_as_verified(self):
        self.faults.activate("frequency_lock_failure")
        task = asyncio.create_task(self.request("set", name="frequency", value=N("6"), unit="GHz"))
        await self.tick(.999)
        self.assertFalse(task.done())
        await self.tick(.001)
        self.assertEqual((await task).fields["code"], "FREQUENCY_LOCK_FAILED")
        self.assertEqual(self.model.snapshot()["actual"]["frequency"], "6")
        self.assertFalse(self.model.snapshot()["actual"]["frequency_verified"])
        self.faults.clear("frequency_lock_failure")
        self.assertEqual((await self.request("get", name="frequency")).verb, "error")

    async def test_clock_faults_coexist_and_historical_utc_survives_recovery(self):
        before = await self.request("status")
        self.faults.activate("clock_untrusted")
        self.faults.activate("synthesizer_failure")
        status = await self.request("status")
        self.assertEqual(status.fields["health"], "fault")
        self.assertEqual(set(status.fields["fault_codes"]), {"SYNTHESIZER_FAILURE", "CLOCK_UNTRUSTED"})
        self.assertEqual(status.fields["booted_at"], before.fields["booted_at"])
        self.faults.clear("synthesizer_failure")
        self.assertEqual((await self.request("get", name="frequency")).verb, "error")
        task = asyncio.create_task(self.request("set", name="frequency", value=N("5"), unit="GHz"))
        await self.tick(.1)
        self.assertEqual((await task).verb, "ok")
        reading = await self.request("get", name="frequency")
        self.assertNotIn("sampled_at", reading.fields)
        self.faults.clear("clock_untrusted")
        self.assertIn("sampled_at", (await self.request("get", name="frequency")).fields)
        self.assertEqual((await self.request("status")).fields["fault_codes"], [])
        codes = {entry["code"] for entry in self.model.snapshot()["incidents"]}
        self.assertIn("CLOCK_UNTRUSTED", codes)
        self.assertIn("SYNTHESIZER_FAILURE", codes)

    async def test_delayed_tuning_action_beyond_one_second_cannot_succeed(self):
        task = asyncio.create_task(self.request("set", name="frequency", value=N("6"), unit="GHz"))
        await self.tick(1.001)
        self.assertEqual((await task).fields["code"], "FREQUENCY_LOCK_FAILED")
        self.assertFalse(self.model.snapshot()["actual"]["frequency_verified"])

    async def test_cancelled_session_wait_does_not_cancel_physical_setting(self):
        task = asyncio.create_task(self.request("set", name="frequency", value=N("6"), unit="GHz"))
        await turns()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        await self.tick(.1)
        self.assertEqual(str((await self.request("get", name="frequency")).fields["value"]), "6")

    async def test_complete_descriptor_boundary_uses_longest_request_id(self):
        boundary = FictitiousReceiverSimulator(ReceiverConfig(hardware_id="x" * 3341), clock=self.clock)
        self.addAsyncCleanup(boundary.close)
        response = (await boundary.handle(Request("get", 4294967295, {}, {"name": "configuration"}), session_id="a")).response
        self.assertEqual(len(encode_response(response)), 4096)
        with self.assertRaisesRegex(ValueError, "4096"):
            FictitiousReceiverSimulator(ReceiverConfig(hardware_id="x" * 3342), clock=self.clock)

    async def test_independent_models_reboot_and_external_fault_continuity(self):
        other = FictitiousReceiverSimulator(ReceiverConfig(), clock=self.clock)
        self.addAsyncCleanup(other.close)
        self.faults.activate("clock_untrusted")
        rule_id = self.faults.schedule("drop_response", when="frequency_set_verified", times=2)
        old = (await self.request("status")).fields["boot_id"]
        reply = await self.model.handle(Request("reboot", 1, {}, {}), session_id="a")
        self.assertTrue(reply.reboot_requested)
        self.assertEqual((await self.request("run", name="calibrate")).fields["code"], "BUSY")
        await self.model.reboot()
        self.assertIs(self.model.faults, self.faults)
        status = await self.request("status")
        self.assertNotEqual(old, status.fields["boot_id"])
        self.assertRegex(status.fields["boot_id"], r"^[0-9a-f]{32}$")
        self.assertNotIn("booted_at", status.fields)
        self.assertEqual((await self.request("status", name="scan")).fields["state"], "unknown")
        self.assertEqual(self.faults.snapshot()["rules"][0]["rule_id"], rule_id)
        self.assertEqual(self.faults.snapshot()["rules"][0]["remaining"], 2)
        self.assertEqual(other.snapshot()["reported"]["general"]["health"], "ok")
        json.dumps(self.model.snapshot())


if __name__ == "__main__":
    unittest.main()
