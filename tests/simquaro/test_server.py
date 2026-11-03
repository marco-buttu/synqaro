"""Raw TCP contract tests; no production client participates in the oracle."""

import asyncio
import socket
import unittest
from unittest.mock import patch

from simquaro.models.fictitious_receiver.config import ReceiverConfig
from simquaro.models.fictitious_receiver.faults import receiver_faults as FaultController
from synqaro_protocol.codec import Request
from simquaro.models.fictitious_receiver.model import FictitiousReceiverSimulator
from tests.simquaro.support.clock import VirtualClock

try:
    from simquaro.server import HardwareServer
except ImportError:
    HardwareServer = None


async def turns(count=40):
    for _ in range(count):
        await asyncio.sleep(0)


class RawSessionCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.assertIsNotNone(HardwareServer, "persistent TCP server is missing")
        self.clock = VirtualClock()
        self.faults = FaultController()
        self.model = FictitiousReceiverSimulator(ReceiverConfig(), faults=self.faults, clock=self.clock)
        self.server = HardwareServer(self.model, "127.0.0.1", 0, clock=self.clock)
        self.address = await self.server.start()
        self.peers = []

    async def asyncTearDown(self):
        if not hasattr(self, "server"):
            return
        for _, writer in self.peers:
            writer.close()
            await writer.wait_closed()
        await self.server.close()
        await self.model.close()

    async def connect(self):
        pair = await asyncio.open_connection(*self.address)
        self.peers.append(pair)
        return pair

    async def line(self, reader):
        return await asyncio.wait_for(reader.readline(), 1)

    async def tick(self, seconds):
        await turns()
        self.clock.advance(seconds)
        await turns()


class ServerTests(RawSessionCase):
    async def test_split_coalesced_and_independent_connections(self):
        a, aw = await self.connect()
        b, bw = await self.connect()
        aw.write(b"#get <id=1>: name=fre")
        bw.write(b"#status <id=1>\n")
        self.assertIn(b"#ok <id=1>", await self.line(b))
        aw.write(b"quency\n#status <id=2>\n")
        self.assertIn(b"value=5", await self.line(a))
        self.assertIn(b"#ok <id=2>", await self.line(a))

    async def test_id_admission_precedes_validation_and_overload(self):
        r, w = await self.connect()
        w.write(b"#get: name=frequency\n")
        reply = await self.line(r)
        self.assertIn(b"code=INVALID_ID", reply)
        self.assertNotIn(b"<id=", reply)
        w.write(b"#get <id=1>: name=frequency\n#get <id=2>: name=frequency value=6\n")
        self.assertIn(b"#ok <id=1>", await self.line(r))
        self.assertIn(b"MALFORMED_REQUEST", await self.line(r))
        for frame in (b"#status <id=2>\n", b"#status <id=1>\n"):
            w.write(frame)
            reply = await self.line(r)
            self.assertIn(b"ID_NOT_INCREASING, last_id=2", reply)
            self.assertNotIn(b'last_id="2"', reply)
        w.write(b"#status <id=3, id=4>\n#status <id=3>\n")
        self.assertEqual(await self.line(r), b"#error: code=INVALID_ID\n")
        self.assertIn(b"#ok <id=3>", await self.line(r))
        w.write(b"#status <id=4294967295>\n#status <id=4294967295>\n")
        self.assertIn(b"#ok <id=4294967295>", await self.line(r))
        self.assertIn(b"last_id=4294967295", await self.line(r))

    async def test_exact_frame_boundary_and_oversize_close(self):
        r, w = await self.connect()
        frame = b"#get <id=1>: name=frequency" + b" " * 4068 + b"\n"
        self.assertEqual(len(frame), 4096)
        w.write(frame)
        self.assertIn(b"#ok <id=1>", await self.line(r))
        w.write(b"x" * 4096)
        self.assertEqual(await self.line(r), b"")

    async def test_duplicate_parameter_diagnostic_preserves_bounded_context(self):
        r, w = await self.connect()
        w.write(b"#get <id=1>: name=frequency, name=configuration\n")
        self.assertEqual(await self.line(r), b"#error <id=1>: code=DUPLICATE_PARAMETER, parameter=name\n")
        key = b"x" * 1800
        w.write(b"#get <id=2>: " + key + b"=1, " + key + b"=2\n")
        reply = await self.line(r)
        self.assertIn(b"DUPLICATE_PARAMETER", reply)
        self.assertLess(len(reply), 300)

    async def test_first_byte_deadline_does_not_extend_with_trickle_or_utc(self):
        r, w = await self.connect()
        await self.tick(100)
        w.write(b"#status ")
        await self.tick(1.5)
        w.write(b"<id=1>")
        await self.tick(.501)
        self.assertEqual(await self.line(r), b"")

    async def test_next_frame_in_predecessor_finishing_read_has_own_deadline(self):
        r, w = await self.connect()
        w.write(b"#status <id=1>")
        await self.tick(1.5)
        w.write(b"\n#status <id=2>")
        self.assertIn(b"#ok <id=1>", await self.line(r))
        # Frame 2 began at 1.5, so it may finish until 3.5, not only until 2.
        await self.tick(1.999)
        w.write(b"\n")
        self.assertIn(b"#ok <id=2>", await self.line(r))

    async def test_four_delayed_pending_fifth_rejected_and_consumed(self):
        self.faults.schedule("delay_response", when="response_ready", times=4, parameters={"delay_ms": 2500})
        r, w = await self.connect()
        w.write(b"".join(f"#status <id={n}>\n".encode() for n in range(1, 6)))
        self.assertEqual(await self.line(r), b"#error <id=5>: code=TOO_MANY_PENDING_REQUESTS, limit=4\n")
        w.write(b"#status <id=5>\n")
        self.assertIn(b"ID_NOT_INCREASING", await self.line(r))
        await self.tick(2.5)
        replies = [await self.line(r) for _ in range(4)]
        self.assertEqual({int(line.split(b"id=")[1].split(b">")[0]) for line in replies}, {1, 2, 3, 4})

    async def test_status_during_tuning_and_disconnection_preserves_actions(self):
        r, w = await self.connect()
        w.write(b"#set <id=1>: name=frequency, value=6, unit=GHz\n#status <id=2>\n")
        self.assertIn(b"#ok <id=2>", await self.line(r))
        w.close()
        await w.wait_closed()
        await self.tick(.1)
        self.assertEqual(self.model.snapshot()["actual"]["frequency"], "6")
        r, w = await self.connect()
        w.write(b"#run <id=1>: name=calibrate\n#status <id=2>: name=calibrate\n")
        self.assertIn(b"#accepted <id=1>", await self.line(r))
        self.assertIn(b"state=running", await self.line(r))
        w.close()
        await w.wait_closed()
        await turns()
        self.assertEqual(self.model.snapshot()["reported"]["procedures"]["calibrate"]["state"], "running")

    async def test_seventeenth_connection_refused_before_admission(self):
        for _ in range(16):
            await self.connect()
        r, w = await self.connect()
        self.assertEqual(await self.line(r), b"")

    async def test_reboot_complete_acceptance_before_eof_same_port_and_faults(self):
        old_boot = self.model.boot_id
        self.faults.activate("clock_untrusted")
        r, w = await self.connect()
        other, _ = await self.connect()
        w.write(b"#reboot <id=1>\n")
        self.assertEqual(await self.line(r), b"#accepted <id=1>\n")
        self.assertEqual(await self.line(r), b"")
        self.assertEqual(await self.line(other), b"")
        await turns(100)
        self.assertEqual(await self.server.start(), self.address)
        self.assertNotEqual(self.model.boot_id, old_boot)
        self.assertIs(self.model.faults, self.faults)
        self.assertTrue(self.faults.is_active("clock_untrusted"))
        r, w = await self.connect()
        w.write(b"#status <id=1>\n")
        self.assertIn(self.model.boot_id.encode(), await self.line(r))

    async def test_reboot_send_queue_failure_still_restarts_and_logs_uncertainty(self):
        old = self.model.boot_id
        r, w = await self.connect()
        with patch("simquaro.server._outgoing_bytes", side_effect=OSError("queue unavailable")):
            with self.assertLogs("simquaro.server", "WARNING") as logs:
                w.write(b"#reboot <id=1>\n")
                self.assertEqual(await self.line(r), b"#accepted <id=1>\n")
                self.assertEqual(await self.line(r), b"")
                await turns(100)
        self.assertNotEqual(old, self.model.boot_id)
        self.assertIn("uncertain", " ".join(logs.output))

    async def test_bounded_long_unknown_request_context(self):
        r, w = await self.connect()
        for n, frame in enumerate((b"#" + b"x" * 3800 + b" <id=1>\n",
                                   b'#get <id=2>: name="' + b"x" * 3800 + b'"\n')):
            w.write(frame)
            reply = await self.line(r)
            self.assertIn(f"#error <id={n + 1}>".encode(), reply)
            self.assertLess(len(reply), 4096)

    async def test_nonreading_peer_has_bounded_write_and_timeout_cleanup(self):
        # Suppress real TCP receive-window progress; exercise actual write/drain.
        await self.model.close()
        self.model = FictitiousReceiverSimulator(ReceiverConfig(hardware_id="x" * 3341),
                                                faults=self.faults, clock=self.clock)
        await self.server.close()
        self.server = HardwareServer(self.model, *self.address, clock=self.clock)
        await self.server.start()
        r, w = await self.connect()
        w.transport.pause_reading()
        w.get_extra_info("socket").setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024)
        await turns()
        session = self.server.sessions[0]
        session.writer.get_extra_info("socket").setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
        maximum = 0
        for batch in range(200):
            w.write(b"".join(f"#get <id={batch * 4 + n}>: name=configuration\n".encode()
                             for n in range(1, 5)))
            await turns(20)
            maximum = max(maximum, session.writer.transport.get_write_buffer_size())
            self.assertLessEqual(session.pending_count, 4)
            self.assertLessEqual(maximum, 20480)
            if maximum > 16384:
                break
        self.assertGreater(maximum, 16384, "peer must actually stall writes")
        await self.tick(2.001)
        # Resume the client to consume the ordered EOF/close already requested.
        w.transport.resume_reading()
        await turns(100)
        self.assertTrue(session.writer.is_closing())
        self.assertEqual(session.pending_count, 0)

    async def test_partial_tail_keeps_original_first_byte_deadline(self):
        self.faults.schedule("delay_response", when="response_ready", parameters={"delay_ms": 1500})
        r, w = await self.connect()
        # An invalid-ID diagnostic stalls receive processing without admitting work.
        w.write(b"#status\n#status <id=")
        await self.tick(1.5)
        self.assertEqual(await self.line(r), b"#error: code=INVALID_ID\n")
        await self.tick(.501)
        self.assertEqual(await self.line(r), b"")

    async def test_partial_tail_expires_even_during_delayed_rejection(self):
        self.faults.schedule("delay_response", when="response_ready", parameters={"delay_ms": 60000})
        r, w = await self.connect()
        w.write(b"#status\n#status <id=")
        await self.tick(2.001)
        self.assertEqual(await self.line(r), b"")

    async def test_server_reboot_api_invalidates_sessions_without_disposing_model(self):
        old = self.model.boot_id
        r, _ = await self.connect()
        await self.server.reboot()
        self.assertEqual(await self.line(r), b"")
        self.assertNotEqual(old, self.model.boot_id)
        self.assertEqual(await self.server.start(), self.address)
        await self.server.close()
        reply = await self.model.handle(Request("status", 1, {}, {}), session_id="after-close")
        self.assertEqual(reply.response.verb, "ok")
