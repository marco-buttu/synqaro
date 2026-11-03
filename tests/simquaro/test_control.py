"""Real local control exchanges, independently framed raw JSON oracles."""

import asyncio
import json
from pathlib import Path
import socket
import tempfile
import unittest

from simquaro.models.fictitious_receiver.config import ReceiverConfig
from simquaro.models.fictitious_receiver.faults import receiver_faults as FaultController
from synqaro_protocol.codec import Request
from simquaro.models.fictitious_receiver.model import FictitiousReceiverSimulator
from simquaro.server import HardwareServer
from tests.simquaro.support.clock import VirtualClock

try:
    from simquaro.control import ControlServer, control_request
except ImportError:
    ControlServer = control_request = None


async def turns():
    for _ in range(40):
        await asyncio.sleep(0)


class ControlTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.assertIsNotNone(ControlServer, "local control interface is missing")
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "control.sock"
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.addCleanup(self.sock.close)
        self.sock.bind(str(self.path))
        self.clock = VirtualClock()
        self.faults = FaultController()
        self.model = FictitiousReceiverSimulator(ReceiverConfig(), faults=self.faults, clock=self.clock)
        self.addAsyncCleanup(self.model.close)
        self.server = ControlServer(self.sock, self.model, self.faults, run_token="test-run")
        await self.server.start()
        self.addAsyncCleanup(self.server.close)
        self.peers = []
        self.addAsyncCleanup(self.close_peers)

    async def close_peers(self):
        for _, writer in self.peers:
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass

    async def connect(self):
        pair = await asyncio.open_unix_connection(str(self.path))
        self.peers.append(pair)
        return pair

    async def raw(self, frame, *, eof=False):
        reader, writer = await self.connect()
        writer.write(frame)
        if eof:
            writer.write_eof()
        reply = await asyncio.wait_for(reader.readline(), 3)
        self.assertLessEqual(len(reply), 65536)
        result = json.loads(reply)
        self.assertEqual(result["version"], 1)
        self.assertEqual(await asyncio.wait_for(reader.read(), 1), b"")
        return result

    def assert_error(self, result, code=None):
        self.assertEqual(set(result), {"version", "ok", "error"})
        self.assertIs(result["ok"], False)
        self.assertEqual(set(result["error"]), {"code", "message", "actions"})
        self.assertTrue(result["error"]["message"])
        self.assertTrue(result["error"]["actions"])
        if code:
            self.assertEqual(result["error"]["code"], code)

    async def call(self, action, arguments=None):
        return await control_request(self.path, action, {} if arguments is None else arguments)

    async def test_full_envelope_and_shared_fault_controller(self):
        result = await self.call("fault.activate", {"name": "clock_untrusted"})
        self.assertEqual(result, {"version": 1, "ok": True, "result": {"ok": True}})
        self.assertTrue(self.model.faults.is_active("clock_untrusted"))
        status = await self.call("status")
        self.assertEqual(status["result"]["run_token"], "test-run")
        self.assertEqual(status["result"]["model"]["reported"]["general"]["health"], "fault")
        self.assertEqual(status["result"]["runtime"], {
            "control": "ready", "hardware_listener": "unverified",
            "hardware_communication": "unprobed", "hardware_communication_verified": False})
        self.assertEqual(status["result"]["model"]["actual"]["frequency"], "5")
        self.assertEqual((await self.call("fault.clear", {"name": "clock_untrusted"}))["result"], {"ok": True})
        self.assertFalse(self.faults.is_active("clock_untrusted"))

    async def test_scheduling_status_cancel_and_no_hardware_rule_consumption(self):
        result = await self.call("fault.schedule", {"name": "drop_response", "when": "response_ready"})
        self.assertEqual(result["result"], {"ok": True, "rule_id": "rule-1"})
        for action in ("status", "fault.status", "status"):
            self.assertTrue((await self.call(action))["ok"])
        state = (await self.call("fault.status"))["result"]
        self.assertEqual(state["rules"][0]["remaining"], 1)
        self.assertIsNone(state["last_event"])
        self.assertTrue((await self.call("fault.cancel", {"rule_id": "rule-1"}))["ok"])
        self.assertEqual(self.faults.snapshot()["rules"], [])
        self.assert_error(await self.call("fault.cancel", {"rule_id": "rule-1"}))

    async def test_exact_action_and_argument_whitelist_without_effects(self):
        cases = [(action, {}) for action in ("reboot", "close", "__dict__", "faults.emit", "fault.catalog")]
        cases += [("status", {"extra": 1}), ("fault.status", {"name": "clock_untrusted"}),
                  ("fault.activate", {"name": "clock_untrusted", "when": "response_ready"}),
                  ("fault.clear", {"name": "clock_untrusted", "parameters": {}}),
                  ("fault.cancel", {"rule_id": "rule-1", "name": "clock_untrusted"}),
                  ("fault.schedule", {"name": "clock_untrusted", "when": "response_ready", "extra": 1}),
                  ("fault.activate", {}), ("fault.activate", {"name": True}),
                  ("fault.schedule", {"name": "clock_untrusted", "when": "response_ready", "times": True}),
                  ("fault.schedule", {"name": "clock_untrusted", "when": "response_ready", "times": 1.0}),
                  ("fault.activate", {"name": "clock_untrusted", "parameters": None}),
                  ("fault.schedule", {"name": "delay_response", "when": "response_ready", "parameters": {"delay_ms": 1.5}})]
        old_boot = self.model.boot_id
        for action, arguments in cases:
            with self.subTest(action=action, arguments=arguments):
                self.assert_error(await self.call(action, arguments))
        self.assertEqual(self.faults.snapshot()["active"], [])
        self.assertEqual(self.faults.snapshot()["rules"], [])
        self.assertEqual(self.model.boot_id, old_boot)

    async def test_strict_json_envelopes_and_duplicate_nested_keys(self):
        frames = [b'not-json\n', b'\xff\n', b'[]\n', b'null\n',
                  b'{"version":true,"action":"status","arguments":{}}\n',
                  b'{"version":1.0,"action":"status","arguments":{}}\n',
                  b'{"version":2,"action":"status","arguments":{}}\n',
                  b'{"version":1,"action":"status"}\n',
                  b'{"version":1,"action":"status","arguments":{},"extra":0}\n',
                  b'{"version":1,"action":"status","arguments":[]}\n',
                  b'{"version":1,"action":false,"arguments":{}}\n',
                  b'{"version":1,"version":1,"action":"fault.activate","arguments":{"name":"clock_untrusted"}}\n',
                  b'{"version":1,"action":"fault.activate","arguments":{"name":"clock_untrusted","name":"synthesizer_failure"}}\n',
                  b'{"version":1,"action":"fault.schedule","arguments":{"name":"delay_response","when":"response_ready","parameters":{"delay_ms":1,"delay_ms":2}}}\n',
                  b'{"version":1,"action":"status","arguments":{"x":NaN}}\n',
                  b'{"version":1,"action":"status","arguments":{"x":Infinity}}\n',
                  b'[' * 1100 + b'0' + b']' * 1100 + b'\n']
        for frame in frames:
            with self.subTest(frame=frame[:80]):
                self.assert_error(await self.raw(frame))
        self.assertEqual(self.faults.snapshot()["active"], [])
        self.assertEqual(self.faults.snapshot()["rules"], [])

    async def test_split_request_and_trickle_do_not_extend_exchange_deadline(self):
        reader, writer = await self.connect()
        writer.write(b'{"version":1,"action":"status",')
        await turns()
        writer.write(b'"arguments":{}}\n')
        self.assertTrue(json.loads(await asyncio.wait_for(reader.readline(), 1))["ok"])
        reader, writer = await self.connect()
        writer.write(b'{')
        started = asyncio.get_running_loop().time()
        await asyncio.sleep(1.2)
        writer.write(b'"version":1')
        self.assert_error(json.loads(await asyncio.wait_for(reader.readline(), 1.3)), "TIMEOUT")
        self.assertLess(asyncio.get_running_loop().time() - started, 2.5)

    async def test_exact_request_limit_and_oversize_before_effect(self):
        request = b'{"version":1,"action":"fault.activate","arguments":{"name":"clock_untrusted"}}'
        padded = request + b' ' * (8191 - len(request)) + b'\n'
        self.assertTrue((await self.raw(padded))["ok"])
        self.faults.clear("clock_untrusted")
        self.assert_error(await self.raw(padded[:-1] + b' \n'), "REQUEST_TOO_LARGE")
        self.assertFalse(self.faults.is_active("clock_untrusted"))
        self.assert_error(await self.raw(b'x' * 8192), "REQUEST_TOO_LARGE")

    async def test_incomplete_eof_and_framing_timeout_have_no_effect(self):
        self.assert_error(await self.raw(b'{"version":1', eof=True), "INCOMPLETE_REQUEST")
        reader, writer = await self.connect()
        writer.write(b'{')
        started = asyncio.get_running_loop().time()
        reply = json.loads(await asyncio.wait_for(reader.readline(), 2.5))
        self.assert_error(reply, "TIMEOUT")
        self.assertLess(asyncio.get_running_loop().time() - started, 2.5)
        self.assertEqual(self.faults.snapshot()["active"], [])

    async def test_only_first_request_on_connection_executes(self):
        reader, writer = await self.connect()
        writer.write(b'{"version":1,"action":"status","arguments":{}}\n'
                     b'{"version":1,"action":"fault.activate","arguments":{"name":"clock_untrusted"}}\n')
        self.assertTrue(json.loads(await reader.readline())["ok"])
        self.assertEqual(await reader.read(), b"")
        self.assertFalse(self.faults.is_active("clock_untrusted"))

    async def test_four_clients_and_capacity_released_after_disconnect(self):
        first = [await self.connect() for _ in range(4)]
        await turns()
        extra, _ = await self.connect()
        try:
            self.assertEqual(await asyncio.wait_for(extra.read(), 1), b"")
        except ConnectionResetError:
            pass
        first[0][1].close()
        await first[0][1].wait_closed()
        await turns()
        self.assertTrue((await self.call("status"))["ok"])

    async def test_close_does_not_unlink_runtime_owned_path(self):
        await self.server.close()
        self.assertTrue(self.path.is_socket())
        await self.server.close()

    async def test_shutdown_closes_admitted_stream_before_handler_first_turn(self):
        # Real streams reproduce acceptance immediately followed by shutdown,
        # before the scheduled handler has entered its try/finally block.
        left, right = socket.socketpair()
        reader, writer = await asyncio.open_unix_connection(sock=left)
        peer = await asyncio.open_unix_connection(sock=right)
        self.peers.extend(((reader, writer), peer))
        self.server._connect(reader, writer)
        await self.server.close()
        self.assertEqual(await asyncio.wait_for(peer[0].read(), .1), b"")

    async def test_raw_action_and_argument_rejection_precedes_mutation(self):
        frames = [b'{"version":1,"action":"reboot","arguments":{}}\n',
                  b'{"version":1,"action":"fault.activate","arguments":{"name":"clock_untrusted","extra":1}}\n',
                  b'{"version":1,"action":"fault.schedule","arguments":{"name":"delay_response","when":"response_ready","parameters":{"delay_ms":true}}}\n']
        for frame in frames:
            self.assert_error(await self.raw(frame))
        self.assertEqual(self.faults.snapshot()["active"], [])
        self.assertEqual(self.faults.snapshot()["rules"], [])

    async def test_listener_state_is_verified_without_protocol_probe(self):
        await self.server.close()
        hardware = HardwareServer(self.model, "127.0.0.1", 0, clock=self.clock)
        self.addAsyncCleanup(hardware.close)
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.bind(str(Path(self.directory.name) / "attached.sock"))
        attached = ControlServer(sock, self.model, self.faults, run_token="attached", hardware_server=hardware)
        self.addAsyncCleanup(attached.close)
        await attached.start()
        path = Path(self.directory.name) / "attached.sock"
        self.assertEqual((await control_request(path, "status", {}))["result"]["runtime"]["hardware_listener"], "closed")
        await hardware.start()
        self.faults.schedule("drop_response", when="response_ready")
        result = await control_request(path, "status", {})
        self.assertEqual(result["result"]["runtime"]["hardware_listener"], "listening")
        self.assertFalse(result["result"]["runtime"]["hardware_communication_verified"])
        self.assertEqual(self.faults.snapshot()["rules"][0]["remaining"], 1)
        await hardware.close()
        self.assertEqual((await control_request(path, "status", {}))["result"]["runtime"]["hardware_listener"], "closed")

    async def test_control_stays_functional_during_drop_delay_and_corruption(self):
        hardware = HardwareServer(self.model, "127.0.0.1", 0, clock=self.clock)
        address = await hardware.start()
        self.addAsyncCleanup(hardware.close)
        for name, parameters in (("drop_response", {}), ("delay_response", {"delay_ms": 60000}), ("malformed_response", {})):
            with self.subTest(name=name):
                await self.call("fault.schedule", {"name": name, "when": "response_ready", "parameters": parameters})
                reader, writer = await asyncio.open_connection(*address)
                self.peers.append((reader, writer))
                writer.write(b'#status <id=1>\n')
                await turns()
                self.assertTrue((await self.call("status"))["ok"])
                self.assertTrue((await self.call("fault.activate", {"name": "clock_untrusted"}))["ok"])
                if name == "malformed_response":
                    self.assertNotIn(b'#ok <id=1>:', await asyncio.wait_for(reader.readline(), 1))
                else:
                    self.assertEqual(len(reader._buffer), 0)
                writer.close()
                await writer.wait_closed()
                await turns()

    async def test_clear_retains_failed_procedure(self):
        await self.call("fault.schedule", {"name": "calibration_reference_unavailable", "when": "calibrate_reference_measurement"})
        reply = await self.model.handle(Request("run", 1, {}, {"name": "calibrate"}), session_id="test")
        self.assertEqual(reply.response.verb, "accepted")
        await turns()
        self.clock.advance(.1)
        await turns()
        self.clock.advance(.9)
        await turns()
        before = (await self.call("status"))["result"]["model"]["reported"]["procedures"]["calibrate"]
        self.assertEqual(before["state"], "failed")
        self.assertTrue((await self.call("fault.clear", {"name": "calibration_reference_unavailable"}))["ok"])
        after = (await self.call("status"))["result"]["model"]["reported"]["procedures"]["calibrate"]
        self.assertEqual(before, after)

    async def test_rule_capacity_and_invalid_fault_errors_preserve_state(self):
        for _ in range(64):
            self.assertTrue((await self.call("fault.schedule", {"name": "clock_untrusted", "when": "response_ready", "times": 4294967295}))["ok"])
        old = self.faults.snapshot()
        self.assert_error(await self.call("fault.schedule", {"name": "clock_untrusted", "when": "response_ready"}))
        self.assert_error(await self.call("fault.activate", {"name": "nonexistent"}))
        self.assertEqual(self.faults.snapshot(), old)
        self.assertTrue((await self.call("status"))["ok"])

    async def test_oversize_result_is_explicit_and_not_truncated(self):
        original = self.model.snapshot
        self.model.snapshot = lambda: {"large": "x" * 65536}
        self.assert_error(await self.call("status"), "RESULT_TOO_LARGE")
        self.model.snapshot = original
        self.assertTrue((await self.call("status"))["ok"])

    async def test_exact_response_size_and_runtime_token_validation(self):
        original = self.model.snapshot
        self.model.snapshot = lambda: {"large": ""}
        reader, writer = await self.connect()
        writer.write(b'{"version":1,"action":"status","arguments":{}}\n')
        baseline = len(await reader.readline())
        self.model.snapshot = lambda: {"large": "x" * (65536 - baseline)}
        reader, writer = await self.connect()
        writer.write(b'{"version":1,"action":"status","arguments":{}}\n')
        frame = await reader.readline()
        self.assertEqual(len(frame), 65536)
        self.assertTrue(json.loads(frame)["ok"])
        self.model.snapshot = lambda: {"large": "x" * (65537 - baseline)}
        self.assert_error(await self.call("status"), "RESULT_TOO_LARGE")
        self.model.snapshot = original
        for token in ("", "x" * 129, "bad\nidentity", False):
            with self.subTest(token=token):
                with self.assertRaises(ValueError):
                    ControlServer(self.sock, self.model, self.faults, run_token=token)

    async def test_nonreading_client_timeout_never_appends_second_response(self):
        original = self.model.snapshot
        self.model.snapshot = lambda: {"large": ""}
        baseline = len(json.dumps((await self.call("status")), separators=(",", ":")).encode()) + 1
        self.model.snapshot = lambda: {"large": "x" * (65536 - baseline)}
        reader, writer = await self.connect()
        writer.transport.pause_reading()
        await turns()
        server_writer = next(iter(self.server._clients.values()))
        server_writer.get_extra_info("socket").setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1024)
        writer.write(b'{"version":1,"action":"status","arguments":{}}\n')
        await turns()
        self.assertGreater(server_writer.transport.get_write_buffer_size(), 0)
        self.assertLessEqual(server_writer.transport.get_write_buffer_size(), 65536)
        await asyncio.sleep(2.1)
        writer.transport.resume_reading()
        data = await asyncio.wait_for(reader.read(), 1)
        self.assertLessEqual(len(data), 65536)
        self.assertLessEqual(data.count(b'\n'), 1)
        self.assertTrue(server_writer.is_closing())
        self.model.snapshot = original


class ClientTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "oracle.sock"
        self.tasks = set()
        self.writers = []

    async def endpoint(self, reply, *, delay=0):
        async def serve(reader, writer):
            self.writers.append(writer)
            try:
                await reader.readline()
                await asyncio.sleep(delay)
                writer.write(reply)
                await writer.drain()
            except (ConnectionError, OSError):
                pass
            finally:
                writer.close()
                await writer.wait_closed()

        def connect(reader, writer):
            task = asyncio.create_task(serve(reader, writer))
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)

        server = await asyncio.start_unix_server(connect, path=str(self.path))
        self.addAsyncCleanup(self.stop_endpoint, server)

    async def stop_endpoint(self, server):
        server.close()
        tasks = tuple(self.tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        for writer in self.writers:
            writer.close()
            await writer.wait_closed()
        await server.wait_closed()

    async def test_connection_failure_returns_actionable_envelope(self):
        self.assertIsNotNone(control_request, "local control client is missing")
        with tempfile.TemporaryDirectory() as directory:
            result = await control_request(Path(directory) / "absent.sock", "status", {})
        self.assertFalse(result["ok"])
        self.assertEqual(result["version"], 1)
        self.assertTrue(result["error"]["actions"])

    async def test_nonfinite_numeric_overflow_is_not_accepted_as_strict_json(self):
        await self.endpoint(b'{"version":1,"ok":true,"result":{"value":1e999}}\n')
        result = await control_request(self.path, "status", {})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "INVALID_JSON")

    async def test_client_bounds_timeout_and_no_replay(self):
        await self.endpoint(b'{"version":1,"ok":true,"result":{}}\n', delay=.2)
        result = await control_request(self.path, "fault.activate", {"name": "clock_untrusted"}, timeout=.02)
        self.assertEqual(result["error"]["code"], "TIMEOUT")
        self.assertEqual(len(self.writers), 1)
        for timeout in (0, -1, True, float("nan"), float("inf"), 2.1):
            result = await control_request(self.path, "status", {}, timeout=timeout)
            self.assertEqual(result["error"]["code"], "INVALID_TIMEOUT")
        result = await control_request(self.path, "fault.activate", {"name": "x" * 8192})
        self.assertEqual(result["error"]["code"], "REQUEST_TOO_LARGE")
        self.assertEqual(len(self.writers), 1)

    async def test_client_rejects_oversized_response(self):
        await self.endpoint(b'x' * 65536 + b'\n')
        result = await control_request(self.path, "status", {})
        self.assertEqual(result["error"]["code"], "RESPONSE_TOO_LARGE")

    async def test_client_rejects_invalid_response_envelope(self):
        await self.endpoint(b'{"version":1,"ok":true,"result":{},"extra":false}\n')
        result = await control_request(self.path, "status", {})
        self.assertEqual(result["error"]["code"], "INVALID_RESPONSE")

    async def test_client_preserves_structured_failure_envelope(self):
        response = {"version": 1, "ok": False, "error": {
            "code": "TEST_FAILURE", "message": "Failure context", "actions": ["Correct test condition."]}}
        await self.endpoint(json.dumps(response).encode() + b'\n')
        self.assertEqual(await control_request(self.path, "status", {}), response)
