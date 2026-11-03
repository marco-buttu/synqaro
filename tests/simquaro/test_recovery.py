"""Uncertainty is retained independently of recovery and newly acquired state."""

import asyncio
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from simquaro.config import InstanceConfig
from simquaro.control import control_request
from simquaro.faults import FaultEffect, FaultRule, Scenario
from synqaro_protocol.codec import NumericToken
from simquaro.runtime import Runtime
from tests.simquaro.test_conformance import DESCRIPTOR, ScriptedClientCase, GENERAL, ok, wire_id
from tests.simquaro.test_server import RawSessionCase, turns

try:
    from tests.simquaro.support.client import ConformanceClient, LocalFailure
except ImportError:
    ConformanceClient = LocalFailure = None


class RecoveryEofTests(unittest.IsolatedAsyncioTestCase):
    async def _recover_after_eof(self, eof_after):
        """Real stream parsing; only connection opening is replaced, no sockets."""
        from tests.simquaro.support.clock import VirtualClock
        clock = VirtualClock()
        client = ConformanceClient("memory-peer", 1, clock=clock)
        self.addAsyncCleanup(client.close)
        next_connection = asyncio.Event()
        writers = []

        class PeerWriter:
            def __init__(self, reader, fail_after):
                self.reader, self.fail_after = reader, fail_after
                self.closing = False
                self.transport = self

            def write(self, frame):
                request_id = wire_id(frame)
                if b'name="configuration"' in frame:
                    fields = DESCRIPTOR
                elif frame.startswith(b"#get"):
                    fields = b'name=frequency, value=6, unit=GHz'
                else:
                    fields = GENERAL
                self.reader.feed_data(ok(request_id, fields))
                if request_id == self.fail_after:
                    self.reader.feed_eof()

            async def drain(self):
                await asyncio.sleep(0)

            def is_closing(self):
                return self.closing

            def close(self):
                self.closing = True
                self.reader.feed_eof()

            abort = close

            async def wait_closed(self):
                await asyncio.sleep(0)

        attempts = 0
        async def open_connection(*args, **kwargs):
            nonlocal attempts
            attempts += 1
            if attempts == 2:
                await next_connection.wait()
            reader = asyncio.StreamReader()
            writer = PeerWriter(reader, eof_after if attempts == 1 else None)
            writers.append(writer)
            return reader, writer

        with patch("asyncio.open_connection", new=open_connection):
            if eof_after == 3:
                client._affected.add(("get", "frequency"))
            client._start_recovery(direct=True)
            await turns(100)
            self.assertFalse(client.writes_enabled, "EOF cannot leave bootstrap readiness enabled")
            self.assertNotIn(("get", "frequency"), client.refreshed,
                             "EOF cannot commit the last refresh from the retired session")
            # Failed bootstrap may pause five seconds; failed refresh retries immediately.
            for _ in range(10):
                if attempts >= 2:
                    break
                clock.advance(.5)
                await turns(100)
            self.assertEqual(attempts, 2, "a coalesced EOF must keep recovery reconnecting")
            self.assertFalse(client.writes_enabled, "new TCP still needs live descriptor/status validation")
            next_connection.set()
            await turns(120)
            self.assertTrue(client.writes_enabled)
            self.assertFalse(writers[-1].is_closing())
            self.assertFalse(client._recovering)
            if eof_after == 3:
                self.assertEqual(str(client.refreshed[("get", "frequency")].fields["value"]), "6")

    async def test_eof_after_reconnect_bootstrap_status_continues_recovery(self):
        await self._recover_after_eof(2)

    async def test_eof_after_last_refresh_continues_recovery_without_committing_stale_state(self):
        await self._recover_after_eof(3)


class RecoveryTests(ScriptedClientCase):
    async def test_lost_set_coalesces_probe_refresh_blocks_writes_and_never_replays(self):
        client = await self.client()
        async def behavior(connection, frame, writer):
            if wire_id(frame) in (3, 4):
                return
            if frame.startswith(b"#get"):
                writer.write(ok(wire_id(frame), b'name=frequency, value=6, unit=GHz'))
            else:
                writer.write(ok(wire_id(frame)))
        self.behavior = behavior
        setting = asyncio.create_task(client.request("set", {"name": "frequency", "value": NumericToken("6"), "unit": "GHz"}))
        reading = asyncio.create_task(client.request("get", {"name": "frequency"}))
        await self.tick(2)
        for request in (setting, reading):
            with self.assertRaises(LocalFailure) as failure:
                await request
            self.assertTrue(failure.exception.uncertain)
        await turns(100)
        self.assertEqual([f for _, f in self.frames if f.startswith(b"#status")],
                         [b'#status <id=2>\n', b'#status <id=5>\n'])
        self.assertEqual(str(client.refreshed[("get", "frequency")].fields["value"]), "6")
        self.assertEqual(len([f for _, f in self.frames if f.startswith(b"#set")]), 1)
        self.assertEqual(len(client.uncertainties), 2)
        self.assertEqual(self.connections, 1)

    async def test_new_modification_is_blocked_until_probe_and_refresh_finish(self):
        client = await self.client()
        self.behavior = lambda *args: asyncio.sleep(0)
        request = asyncio.create_task(client.request("set", {"name": "frequency", "value": NumericToken("6"), "unit": "GHz"}))
        await self.tick(2)
        with self.assertRaises(LocalFailure):
            await request
        with self.assertRaises(LocalFailure) as failure:
            await client.request("run", {"name": "calibrate"})
        self.assertEqual(failure.exception.code, "RECOVERY_IN_PROGRESS")
        self.assertFalse(any(f.startswith(b"#run") for _, f in self.frames))

    async def test_unusable_refresh_does_not_release_modifications(self):
        client = await self.client()
        async def behavior(connection, frame, writer):
            if wire_id(frame) == 3 and connection == 1:
                return
            if frame.startswith(b"#get"):
                writer.write(ok(wire_id(frame), b'name=frequency, value="invented", unit=GHz'))
            else:
                writer.write(ok(wire_id(frame)))
        self.behavior = behavior
        request = asyncio.create_task(client.request("set", {"name": "frequency", "value": NumericToken("6"), "unit": "GHz"}))
        await self.tick(2)
        with self.assertRaises(LocalFailure):
            await request
        await turns(120)
        self.assertFalse(client.writes_enabled)
        self.assertNotIn(("get", "frequency"), client.refreshed)

    async def test_valid_fault_probe_retains_tcp_and_separates_health(self):
        client = await self.client()
        async def behavior(connection, frame, writer):
            if wire_id(frame) == 3:
                return
            writer.write(ok(wire_id(frame), GENERAL.replace(b'health=ok', b'health=fault').replace(
                b'fault_codes=[]', b'fault_codes=[CLOCK_UNTRUSTED]')))
        self.behavior = behavior
        request = asyncio.create_task(client.request("status"))
        await self.tick(2)
        with self.assertRaises(LocalFailure):
            await request
        await turns(100)
        self.assertEqual(client.general.fields["health"], "fault")
        self.assertEqual(self.connections, 1)
        self.assertTrue(client.writes_enabled)

    async def test_failed_probe_reconnects_discovers_and_refreshes_without_replay(self):
        client = await self.client()
        async def behavior(connection, frame, writer):
            if connection == 1:
                return
            writer.write(ok(wire_id(frame), b'name=frequency, value=6, unit=GHz'))
        self.behavior = behavior
        request = asyncio.create_task(client.request("set", {"name": "frequency", "value": NumericToken("6"), "unit": "GHz"}))
        await self.tick(2)
        with self.assertRaises(LocalFailure):
            await request
        await self.tick(2)
        self.assertEqual(self.connections, 2)
        new = [frame for connection, frame in self.frames if connection == 2]
        self.assertEqual(new, [b'#get <id=1>: name="configuration"\n', b'#status <id=2>\n',
                               b'#get <id=3>: name="frequency"\n'])
        self.assertEqual(len([f for _, f in self.frames if f.startswith(b"#set")]), 1)

    async def test_reconnect_attempts_have_two_second_limit_five_second_pause_and_cancel(self):
        client = await self.client()
        self.behavior = lambda *args: asyncio.sleep(0)
        starts = []
        active = 0
        async def hanging_connect(*args, **kwargs):
            nonlocal active
            starts.append(self.clock.monotonic())
            active += 1
            self.assertEqual(active, 1)
            try:
                await asyncio.Future()
            finally:
                active -= 1
        with patch("asyncio.open_connection", new=hanging_connect):
            request = asyncio.create_task(client.request("status"))
            await self.tick(2)
            with self.assertRaises(LocalFailure):
                await request
            await self.tick(2)
            self.assertEqual(starts, [4])
            await self.tick(1.999)
            self.assertEqual(active, 1)
            await self.tick(.001)
            self.assertEqual(active, 0)
            await self.tick(4.999)
            self.assertEqual(starts, [4])
            await self.tick(.001)
            self.assertEqual(starts, [4, 11])
            await client.close()
            self.assertEqual(active, 0)

    async def test_late_reply_is_evidence_not_retroactive_result_or_state_update(self):
        client = await self.client()
        async def behavior(connection, frame, writer):
            if wire_id(frame) != 3:
                writer.write(ok(wire_id(frame)))
        self.behavior = behavior
        request = asyncio.create_task(client.request("get", {"name": "frequency"}))
        await self.tick(2)
        with self.assertRaises(LocalFailure):
            await request
        self.writers[0].write(ok(3, b'name=frequency, value=9, unit=GHz'))
        await turns(100)
        self.assertTrue(any(e.kind == "late" for e in client.evidence))
        self.assertNotIn(("get", "frequency"), client.refreshed)
        self.assertEqual(len(client.uncertainties), 1)

    async def test_id_exhaustion_drains_then_rotates_without_wrapping(self):
        client = await self.client()
        client._next_id = 4294967295  # Reach boundary without four billion exchanges.
        async def behavior(connection, frame, writer):
            if connection > 1:
                writer.write(ok(wire_id(frame)))
        self.behavior = behavior
        last = asyncio.create_task(client.request("status"))
        await turns(60)
        following = asyncio.create_task(client.request("status"))
        await turns(60)
        self.assertEqual(self.connections, 1, "pending final-ID response must drain before rotation")
        self.writers[0].write(ok(4294967295))
        _, response = await asyncio.wait_for(asyncio.gather(last, following), 1)
        self.assertEqual(response.request_id, 3)
        self.assertIn((1, b'#status <id=4294967295>\n'), self.frames)
        self.assertEqual(self.connections, 2)
        self.assertFalse(any(b'id=0>' in frame for _, frame in self.frames))

    async def test_exhaustion_revalidation_failure_cannot_admit_prechecked_write(self):
        client = await self.client()
        client._next_id = 4294967295
        await client.request("status")
        self.descriptor = self.descriptor.replace(b'example-receiver-01', b'wrong-target')
        with self.assertRaises(LocalFailure):
            await client.request("set", {"name": "frequency", "value": NumericToken("6"), "unit": "GHz"})
        self.assertFalse(any(frame.startswith(b"#set") for _, frame in self.frames))

    async def test_disconnect_marks_all_pending_uncertain_before_new_session_refresh(self):
        client = await self.client()
        async def behavior(connection, frame, writer):
            if connection == 1 and wire_id(frame) == 4:
                writer.close()
            elif connection > 1:
                writer.write(ok(wire_id(frame), b'name=frequency, value=6, unit=GHz'))
        self.behavior = behavior
        requests = [asyncio.create_task(client.request("set", {"name": "frequency", "value": NumericToken("6"), "unit": "GHz"})),
                    asyncio.create_task(client.request("get", {"name": "frequency"}))]
        results = await asyncio.wait_for(asyncio.gather(*requests, return_exceptions=True), 1)
        await turns(160)
        self.assertTrue(all(isinstance(result, LocalFailure) and result.uncertain for result in results))
        self.assertEqual(len(client.uncertainties), 2)
        self.assertEqual(str(client.refreshed[("get", "frequency")].fields["value"]), "6")
        self.assertEqual(self.connections, 2)

    async def test_failed_probe_disconnects_other_pending_before_its_later_deadline(self):
        client = await self.client()
        async def behavior(connection, frame, writer):
            if connection == 1 and wire_id(frame) == 5:
                writer.write(b'#error <id=5>: code=STATUS_UNAVAILABLE\n')
            elif connection > 1:
                writer.write(ok(wire_id(frame)))
        self.behavior = behavior
        first = asyncio.create_task(client.request("status"))
        await self.tick(1)
        second = asyncio.create_task(client.request("status"))
        await self.tick(1)
        try:
            self.assertTrue(second.done(), "closing the old session must fail its remaining pending request immediately")
            for request in (first, second):
                with self.assertRaises(LocalFailure):
                    await request
            self.assertEqual(len(client.uncertainties), 2)
        finally:
            for request in (first, second):
                request.cancel()
            await asyncio.gather(first, second, return_exceptions=True)

    async def test_exhausted_timeout_bypasses_impossible_probe_preserves_uncertainty(self):
        client = await self.client()
        client._next_id = 4294967295
        async def behavior(connection, frame, writer):
            if connection != 1:
                writer.write(ok(wire_id(frame)))
        self.behavior = behavior
        request = asyncio.create_task(client.request("status"))
        await self.tick(2)
        with self.assertRaises(LocalFailure):
            await request
        await turns(100)
        self.assertEqual(self.connections, 2)
        self.assertEqual([frame for connection, frame in self.frames if connection == 1][-1],
                         b'#status <id=4294967295>\n')
        self.assertEqual(len(client.uncertainties), 1)

    async def test_incomplete_reply_deadline_and_oversize_close_broken_transport(self):
        for payload in (b'#ok <id=3>: value=5', b'x' * 4096):
            with self.subTest(payload=payload[:20]):
                client = await self.client()
                async def behavior(connection, frame, writer):
                    writer.write(payload)
                self.behavior = behavior
                request = asyncio.create_task(client.request("status"))
                await self.tick(2)
                with self.assertRaises(LocalFailure):
                    await request
                self.assertTrue(any(e.kind == "framing" for e in client.evidence))
                await client.close()
                self.behavior = None


class ReceiverRecoveryTests(RawSessionCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.clients = []

    async def asyncTearDown(self):
        for client in self.clients:
            await client.close()
        # Reboot's bounded Linux transmit observation uses the injected clock.
        if self.server._restart_task is not None:
            await self.tick(1.001)
        await asyncio.wait_for(super().asyncTearDown(), 3)

    async def conforming(self):
        self.assertIsNotNone(ConformanceClient, "test-only conforming client is missing")
        client = ConformanceClient(*self.address, clock=self.clock)
        self.clients.append(client)
        await client.connect()
        return client

    async def test_applied_set_lost_reply_reacquires_actual_frequency(self):
        client = await self.conforming()
        self.faults.schedule("drop_response", when="frequency_set_verified")
        request = asyncio.create_task(client.request("set", {"name": "frequency", "value": NumericToken("6"), "unit": "GHz"}))
        await self.tick(.1)
        self.assertEqual(self.model.snapshot()["actual"]["frequency"], "6")
        await self.tick(1.9)
        with self.assertRaises(LocalFailure):
            await request
        await turns(100)
        self.assertEqual(str(client.refreshed[("get", "frequency")].fields["value"]), "6")
        self.assertEqual(len(self.server.sessions), 1)

    async def test_read_failure_is_not_calibration_unavailability_or_guessed_frequency(self):
        client = await self.conforming()
        self.faults.activate("frequency_read_failure")
        response = await client.request("get", {"name": "frequency"})
        self.assertEqual(response.fields["code"], "FREQUENCY_READ_FAILED")
        self.assertNotIn("value", response.fields)
        self.assertEqual(self.model.snapshot()["actual"]["frequency"], "5")
        self.assertIn("could not be read reliably", client.evidence[-1].message)
        self.faults.clear("frequency_read_failure")
        await client.request("run", {"name": "calibrate"})
        response = await client.request("get", {"name": "frequency"})
        self.assertEqual(response.fields, {"code": "VALUE_UNAVAILABLE", "reason": "CALIBRATING"})

    async def test_reference_failure_after_acceptance_remains_failed_after_clearing(self):
        client = await self.conforming()
        self.faults.schedule("calibration_reference_unavailable", when="calibrate_reference_measurement")
        self.assertEqual((await client.request("run", {"name": "calibrate"})).verb, "accepted")
        await self.tick(.1)
        await self.tick(.9)
        self.assertTrue(self.faults.is_active("calibration_reference_unavailable"))
        status = await client.request("status", {"name": "calibrate"})
        self.assertEqual(status.fields["state"], "failed")
        self.assertEqual(status.fields["error_code"], "CALIBRATION_REFERENCE_UNAVAILABLE")
        general = await client.request("status")
        self.assertFalse(general.fields["calibrated"])
        self.assertEqual(general.fields["health"], "ok")
        self.faults.clear("calibration_reference_unavailable")
        self.assertEqual((await client.request("status", {"name": "calibrate"})).fields["state"], "failed")

    async def test_lost_calibration_and_scan_acceptance_queries_named_state_without_restart(self):
        for name in ("calibrate", "scan"):
            with self.subTest(name=name):
                client = await self.conforming()
                self.faults.schedule("drop_response", when="response_ready")
                fields = {"name": name}
                if name == "scan":
                    fields.update(start=NumericToken("5"), stop=NumericToken("6"), unit="GHz", dwell_ms=NumericToken("1000"))
                request = asyncio.create_task(client.request("run", fields))
                # Let each ordinary tuning finish within its unchanged 1 s limit.
                for elapsed in (.1, 1, .1, .8):
                    await self.tick(elapsed)
                with self.assertRaises(LocalFailure):
                    await request
                await turns(100)
                self.assertEqual(client.refreshed[("status", name)].fields["state"], "running")
                self.assertEqual(self.model.snapshot()["reported"]["procedures"][name]["state"], "running")
                await self.server.reboot()
                await client.close()

    async def test_lost_read_next_get_is_new_acquisition_after_external_change(self):
        client = await self.conforming()
        self.faults.schedule("drop_response", when="response_ready")
        request = asyncio.create_task(client.request("get", {"name": "frequency"}))
        await self.tick(2)
        with self.assertRaises(LocalFailure):
            await request
        reader, writer = await self.connect()
        writer.write(b"#set <id=1>: name=frequency, value=7, unit=GHz\n")
        await self.tick(.1)
        self.assertIn(b'value=7', await self.line(reader))
        response = await client.request("get", {"name": "frequency"})
        self.assertEqual(str(response.fields["value"]), "7")
        self.assertEqual(response.fields["sampled_at"], "2026-01-01T00:00:02.100000Z")

    async def test_reconnect_keeps_boot_reboot_changes_it_and_preserves_injections(self):
        client = await self.conforming()
        initial = client.general.fields["boot_id"]
        self.faults.activate("clock_untrusted")
        rule = self.faults.schedule("calibration_reference_unavailable", when="calibrate_reference_measurement", times=2)
        await client.close()
        client = await self.conforming()
        self.assertEqual(client.general.fields["boot_id"], initial)
        response = await client.request("reboot")
        self.assertEqual(response.verb, "accepted")
        # Allow the OS to acknowledge bytes, then drive the virtual poll sleeper.
        await asyncio.sleep(.05)
        await self.tick(.02)
        await turns(200)
        self.assertNotEqual(self.model.boot_id, initial)
        # An immediate TCP attempt can race the restarting listener; honor its pause.
        if not client.writes_enabled:
            await self.tick(5)
        self.assertNotEqual(client.general.fields["boot_id"], initial)
        self.assertEqual(client.general.fields["fault_codes"], ["CLOCK_UNTRUSTED"])
        self.assertEqual(self.faults.snapshot()["rules"][0]["rule_id"], rule)
        self.assertEqual(self.faults.snapshot()["rules"][0]["remaining"], 2)


class ProcessResetTests(unittest.IsolatedAsyncioTestCase):
    async def test_process_restart_reapplies_initial_scenario_not_ad_hoc_conditions_or_counters(self):
        # Existing pidfd runtime owns/cleans the real child; no new process manager.
        log = tempfile.TemporaryFile()
        saved_stderr = os.dup(2)
        os.dup2(log.fileno(), 2)
        self.addCleanup(log.close)
        self.addCleanup(os.close, saved_stderr)
        self.addCleanup(os.dup2, saved_stderr, 2)
        temporary = tempfile.TemporaryDirectory(prefix="sq-acceptance-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name) / "run"
        runtime = Runtime(root)
        config = InstanceConfig("receiver-a", "fictitious_receiver", "127.0.0.1", 0)
        scenario = Scenario((FaultEffect("calibration_reference_unavailable"),),
                            (FaultRule("drop_response", "frequency_set_verified", times=2),))
        children = []
        async def cleanup():
            for child in children:
                if child is not None:
                    await child.terminate()
                    await asyncio.wait_for(child.wait(), 3)
        self.addAsyncCleanup(cleanup)
        first = await runtime.start(config, scenario=scenario)
        children.append(first.child)
        self.assertTrue(first.outcome["ok"], first.outcome)
        await control_request(root / "receiver-a.sock", "fault.activate", {"name": "clock_untrusted"})
        await control_request(root / "receiver-a.sock", "fault.cancel", {"rule_id": "rule-1"})
        await control_request(root / "receiver-a.sock", "fault.schedule",
                              {"name": "frequency_read_failure", "when": "response_ready", "times": 3})
        restarted = await runtime.restart(config, scenario=scenario)
        children.append(restarted.child)
        self.assertTrue(restarted.outcome["ok"], restarted.outcome)
        faults = restarted.outcome["status"]["faults"]
        self.assertEqual([effect["name"] for effect in faults["active"]], ["calibration_reference_unavailable"])
        self.assertEqual([(rule["name"], rule["remaining"]) for rule in faults["rules"]], [("drop_response", 2)])
        self.assertNotEqual(first.outcome["status"]["run_token"], restarted.outcome["status"]["run_token"])
