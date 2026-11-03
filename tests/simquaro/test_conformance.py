"""Client conformance against literal wire oracles, never its request encoder."""

import asyncio
import re
import unittest

from synqaro_protocol.codec import NumericToken
from tests.simquaro.support.clock import VirtualClock
from tests.simquaro.test_server import turns

try:
    from tests.simquaro.support.client import ConformanceClient, LocalFailure
except ImportError:
    ConformanceClient = LocalFailure = None


# Hand-transcribed approved fictitious-v1 descriptor, independent of model/codec.
DESCRIPTOR = (
    b'name=configuration, protocol_version=1, hardware_id="example-receiver-01", '
    b'hardware_model=fictitious_receiver, firmware_version="0.1.0", firmware_build="test-build", '
    b'readonly_properties=[configuration], readwrite_properties=[frequency], '
    b'supported_procedures=[calibrate, scan], frequency_min=1, frequency_max=10, '
    b'frequency_unit=GHz, frequency_resolution=0.000001, frequency_rounding=nearest_ties_up, '
    b'max_message_bytes=4096, incomplete_message_timeout_ms=2000, max_pending_requests=4, '
    b'max_tuning_ms=1000, calibrate_timeout_ms=30000, scan_timeout_ms=20000, '
    b'procedure_stop_timeout_ms=5000, scan_points=10, scan_max_dwell_ms=1000, '
    b'calibrate_cancellation=except_finalization, scan_cancellation=always, '
    b'utc_clock_supported=true, sampled_at_properties=[frequency]'
)
GENERAL = (b'health=ok, activity=idle, calibrated=false, fault_codes=[], '
           b'boot_id="11111111111111111111111111111111"')


def wire_id(frame):
    return int(re.search(rb'<id=([0-9]+)>', frame).group(1))


def ok(request_id, fields=GENERAL):
    return b"#ok <id=" + str(request_id).encode() + b">: " + fields + b"\n"


class ScriptedClientCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.assertIsNotNone(ConformanceClient, "test-only conforming client is missing")
        self.clock = VirtualClock()
        self.frames = []
        self.writers = []
        self.handlers = set()
        self.clients = []
        self.behavior = None
        self.descriptor = DESCRIPTOR
        self.connections = 0
        self.peer = await asyncio.start_server(self._peer, "127.0.0.1", 0)
        self.address = self.peer.sockets[0].getsockname()[:2]

    async def _peer(self, reader, writer):
        task = asyncio.current_task()
        self.handlers.add(task)
        self.writers.append(writer)
        self.connections += 1
        connection = self.connections
        try:
            while frame := await reader.readline():
                self.frames.append((connection, frame))
                request_id = wire_id(frame)
                if b'name="configuration"' in frame:
                    writer.write(ok(request_id, self.descriptor))
                elif request_id == 2 and frame == b"#status <id=2>\n":
                    writer.write(ok(request_id))
                elif self.behavior:
                    await self.behavior(connection, frame, writer)
                else:
                    writer.write(ok(request_id))
                await writer.drain()
        except (ConnectionError, asyncio.CancelledError):
            pass
        finally:
            writer.close()
            await writer.wait_closed()
            self.handlers.discard(task)

    async def client(self, **kwargs):
        client = ConformanceClient(*self.address, clock=self.clock, **kwargs)
        self.clients.append(client)
        await client.connect()
        return client

    async def tick(self, seconds):
        await turns(60)
        self.clock.advance(seconds)
        await turns(100)

    async def asyncTearDown(self):
        for client in getattr(self, "clients", []):
            await client.close()
        if not hasattr(self, "peer"):
            return
        self.peer.close()
        await self.peer.wait_closed()
        for writer in self.writers:
            writer.close()
        await asyncio.gather(*(writer.wait_closed() for writer in self.writers), return_exceptions=True)
        for task in tuple(self.handlers):
            task.cancel()
        await asyncio.gather(*self.handlers, return_exceptions=True)


class ConformanceTests(ScriptedClientCase):
    async def test_bootstrap_and_increasing_ids_have_explicit_wire_oracle(self):
        client = await self.client()
        await client.request("get", {"name": "frequency"})
        await client.request("set", {"name": "frequency", "value": NumericToken("5.1234565"), "unit": "GHz"})
        self.assertEqual([frame for _, frame in self.frames], [
            b'#get <id=1>: name="configuration"\n', b'#status <id=2>\n',
            b'#get <id=3>: name="frequency"\n',
            b'#set <id=4>: name="frequency", value=5.1234565, unit="GHz"\n'])

    async def test_fifth_submission_rejected_locally_without_implicit_queue(self):
        client = await self.client()
        self.behavior = lambda *args: asyncio.sleep(0)
        requests = [asyncio.create_task(client.request("status")) for _ in range(4)]
        await turns(100)
        with self.assertRaises(LocalFailure) as failure:
            await client.request("status")
        self.assertEqual(failure.exception.code, "TOO_MANY_PENDING_REQUESTS")
        self.assertEqual(len(self.frames), 6)
        for request in requests:
            request.cancel()
        await asyncio.gather(*requests, return_exceptions=True)

    async def test_reordered_fragmented_coalesced_replies_correlate_independently(self):
        client = await self.client()
        async def behavior(connection, frame, writer):
            if wire_id(frame) == 4:
                writer.write(b'#ok <id=4>: value=4\n#ok <id=3>: val')
                await writer.drain()
                await asyncio.sleep(0)
                writer.write(b'ue=3\n')
        self.behavior = behavior
        a, b = await asyncio.gather(client.request("status"), client.request("status"))
        self.assertEqual((a.request_id, str(a.fields["value"])), (3, "3"))
        self.assertEqual((b.request_id, str(b.fields["value"])), (4, "4"))

    async def test_exact_4096_byte_response_including_lf_is_accepted(self):
        client = await self.client()
        async def behavior(connection, frame, writer):
            prefix = b'#ok <id=3>: value=5'
            reply = prefix + b' ' * (4095 - len(prefix)) + b'\n'
            self.assertEqual(len(reply), 4096)
            writer.write(reply)
        self.behavior = behavior
        response = await client.request("get", {"name": "frequency"})
        self.assertEqual(str(response.fields["value"]), "5")
        self.assertEqual(self.connections, 1)

    async def test_deadline_does_not_accept_completion_after_scheduler_time_jump(self):
        client = await self.client()
        async def stalled_operation():
            # The clock is the actual injected dependency, not a timer mock.
            self.clock.advance(2.001)
            return "late completion"
        with self.assertRaises(TimeoutError):
            await client._bounded(stalled_operation())

    async def test_reserved_foreign_duplicate_and_uncorrelated_diagnostics_do_not_steal_pending(self):
        client = await self.client()
        async def behavior(connection, frame, writer):
            writer.write(b'#error: code=INVALID_ID\n'
                         b'#error <id=3>: code=ID_NOT_INCREASING, last_id=3, rejected_verb=status\n'
                         b'#ok <id=99>: value=99\n' + ok(3) + ok(3))
        self.behavior = behavior
        response = await client.request("status")
        await turns(100)
        self.assertEqual(response.request_id, 3)
        self.assertEqual({e.kind for e in client.evidence},
                         {"uncorrelated", "id_rejection", "foreign", "duplicate"})
        self.assertEqual(self.connections, 1)

    async def test_correlatable_malformed_reply_only_fails_its_request(self):
        client = await self.client()
        async def behavior(connection, frame, writer):
            if wire_id(frame) == 3:
                writer.write(b'#ok <id=3>: value=[\n')
            else:
                writer.write(ok(wire_id(frame)))
        self.behavior = behavior
        a, b = await asyncio.gather(client.request("get", {"name": "frequency"}),
                                    client.request("status"), return_exceptions=True)
        self.assertIsInstance(a, LocalFailure)
        self.assertEqual(a.code, "MALFORMED_RESPONSE")
        self.assertEqual(b.request_id, 4)
        self.assertEqual(self.connections, 1)
        self.assertIn(b'value=[', client.evidence[-1].wire)

    async def test_unattributable_malformed_reply_preserves_original_deadline(self):
        client = await self.client()
        async def behavior(connection, frame, writer):
            if wire_id(frame) == 3:
                writer.write(b"not-a-response\n")
            else:
                writer.write(ok(wire_id(frame)))
        self.behavior = behavior
        request = asyncio.create_task(client.request("get", {"name": "frequency"}))
        await self.tick(1.999)
        self.assertFalse(request.done())
        await self.tick(.001)
        with self.assertRaises(LocalFailure) as failure:
            await request
        self.assertEqual(failure.exception.code, "RESPONSE_TIMEOUT")
        self.assertTrue(any(e.kind == "unattributed_malformed" for e in client.evidence))

    async def test_known_and_unknown_hardware_errors_preserve_context_without_reconnect(self):
        client = await self.client()
        async def behavior(connection, frame, writer):
            request_id = wire_id(frame)
            code = b"FREQUENCY_READ_FAILED" if request_id == 3 else b"FUTURE_SENSOR_ERROR"
            writer.write(b'#error <id=' + str(request_id).encode() + b'>: code=' + code +
                         b', parameter=frequency, description="board detail"\n')
        self.behavior = behavior
        first = await client.request("get", {"name": "frequency"})
        second = await client.request("get", {"name": "frequency"})
        self.assertEqual(first.fields["code"], "FREQUENCY_READ_FAILED")
        self.assertEqual(second.fields["code"], "FUTURE_SENSOR_ERROR")
        self.assertEqual(second.fields["description"], "board detail")
        known, unknown = client.evidence
        self.assertIn("could not be read reliably", known.message)
        self.assertIn("Unrecognized hardware error code", unknown.message)
        self.assertEqual((known.request_id, known.verb, known.target), (3, "get", "frequency"))
        self.assertEqual(known.hardware_id, "example-receiver-01")
        self.assertEqual(known.time_provenance, "client_receipt_utc")
        self.assertIsNotNone(known.received_at)
        self.assertEqual(self.connections, 1)

    async def test_fault_status_and_failed_procedure_include_readable_catalog_evidence(self):
        client = await self.client()
        async def behavior(connection, frame, writer):
            if wire_id(frame) == 3:
                writer.write(ok(3, GENERAL.replace(b'health=ok', b'health=fault').replace(
                    b'fault_codes=[]', b'fault_codes=[CLOCK_UNTRUSTED, SYNTHESIZER_FAILURE]')))
            else:
                writer.write(ok(4, b'name=calibrate, state=failed, error_code=CALIBRATION_REFERENCE_UNAVAILABLE'))
        self.behavior = behavior
        await client.request("status")
        await client.request("status", {"name": "calibrate"})
        messages = [event.message for event in client.evidence]
        self.assertTrue(any("UTC clock is unavailable or untrusted" in message for message in messages))
        self.assertTrue(any("Diagnostics confirm a synthesizer fault" in message for message in messages))
        self.assertTrue(any("calibration reference is unavailable" in message for message in messages))

    async def test_descriptor_rejects_missing_wrong_type_incompatible_and_incoherent_before_write(self):
        cases = (
            (b"protocol_version=1, ", b""),
            (b"protocol_version=1", b'protocol_version="1"'),
            (b"protocol_version=1", b"protocol_version=2"),
            (b'readwrite_properties=[frequency]', b'readwrite_properties=[configuration, frequency]'),
            (b"max_message_bytes=4096", b"max_message_bytes=8192"),
            (b"frequency_resolution=0.000001", b"frequency_resolution=0.001"),
            (b'example-receiver-01', b'wrong-target'),
        )
        for old, new in cases:
            with self.subTest(new=new):
                self.descriptor = DESCRIPTOR.replace(old, new)
                before = len(self.frames)
                client = ConformanceClient(*self.address, clock=self.clock)
                self.clients.append(client)
                with self.assertRaises(LocalFailure) as failure:
                    await client.connect()
                self.assertEqual(failure.exception.code, "INCOMPATIBLE_DESCRIPTOR")
                with self.assertRaises(LocalFailure):
                    await client.request("set", {"name": "frequency", "value": NumericToken("6"), "unit": "GHz"})
                self.assertFalse(any(frame.startswith(b"#set") for _, frame in self.frames[before:]))
                await client.close()

    async def test_explicit_alternate_expected_identity_is_independent_of_descriptor(self):
        self.descriptor = DESCRIPTOR.replace(b'example-receiver-01', b'receiver-b')
        client = await self.client(expected_hardware_id="receiver-b")
        self.assertTrue(client.writes_enabled)

    async def test_descriptor_unrepresentable_number_is_explicit_incompatibility(self):
        self.descriptor = DESCRIPTOR.replace(b'frequency_min=1', b'frequency_min=1e99999999999999999999999999')
        client = ConformanceClient(*self.address, clock=self.clock)
        self.clients.append(client)
        with self.assertRaises(LocalFailure) as failure:
            await client.connect()
        self.assertEqual(failure.exception.code, "INCOMPATIBLE_DESCRIPTOR")

    async def test_admission_rejects_fifth_even_when_first_write_is_backpressured(self):
        client = await self.client()
        gate = asyncio.Event()
        original = client._writer.drain
        async def blocked_drain():
            await gate.wait()
            await original()
        client._writer.drain = blocked_drain
        requests = [asyncio.create_task(client.request("status")) for _ in range(4)]
        await turns(60)
        fifth = asyncio.create_task(client.request("status"))
        await turns(60)
        try:
            self.assertTrue(fifth.done(), "local admission must not wait in the writer queue")
            with self.assertRaises(LocalFailure) as failure:
                await fifth
            self.assertEqual(failure.exception.code, "TOO_MANY_PENDING_REQUESTS")
        finally:
            gate.set()
            await asyncio.gather(*requests, fifth, return_exceptions=True)
