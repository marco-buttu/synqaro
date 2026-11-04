"""Byte transport must not repair diagnostic data or duplicate protocol logic."""

import asyncio
import importlib
import unittest


class TransportTests(unittest.IsolatedAsyncioTestCase):
    def modules(self):
        try:
            return (importlib.import_module("synqaro_protocol.transport"),
                    importlib.import_module("synqaro_protocol.codec"))
        except ImportError:
            self.fail("shared protocol package is missing")

    async def test_arbitrary_oversized_bytes_and_half_close(self):
        transport, _ = self.modules()
        received = asyncio.get_running_loop().create_future()
        async def peer(reader, writer):
            data = await reader.read()
            received.set_result(data)
            writer.write(b"first\x00\xff")
            await writer.drain()
            writer.close()
            await writer.wait_closed()
        server = await asyncio.start_server(peer, "127.0.0.1", 0)
        self.addAsyncCleanup(server.wait_closed)
        self.addCleanup(server.close)
        host, port = server.sockets[0].getsockname()[:2]
        connection = await transport.TcpConnection.open(host, port)
        self.addAsyncCleanup(connection.close)
        payload = b"a\x00\xff" + b"x" * 4097
        await connection.send(payload)
        await connection.shutdown_write()
        self.assertEqual(await asyncio.wait_for(received, 2), payload)
        reply = b""
        while chunk := await connection.receive():
            self.assertLessEqual(len(chunk), 4096)
            reply += chunk
        self.assertEqual(reply, b"first\x00\xff")

    async def test_request_encoder_keeps_numeric_spelling_and_quoted_strings(self):
        _, codec = self.modules()
        request = codec.Request("set", 17, {}, {
            "name": "frequency", "value": codec.NumericToken("5.1234565"), "unit": "GHz"})
        self.assertEqual(codec.encode_request(request),
                         b'#set <id=17>: name="frequency", value=5.1234565, unit="GHz"\n')
        decoded = codec.parse_request(codec.encode_request(request))
        self.assertEqual(decoded.fields, request.fields)
        self.assertEqual(decoded.request_id, 17)

    async def test_request_encoder_rejects_unsafe_metadata_and_nested_lists(self):
        _, codec = self.modules()
        for request in (codec.Request("get", 0, {}, {}),
                        codec.Request("get", 1, {"id": codec.NumericToken("2")}, {}),
                        codec.Request("set", 1, {}, {"value": [["a"]]})):
            with self.subTest(request=request), self.assertRaises(codec.ProtocolError):
                codec.encode_request(request)

    async def test_send_deadline_is_not_reset_by_each_chunk(self):
        transport, _ = self.modules()
        from tests.simquaro.support.clock import VirtualClock
        clock = VirtualClock()
        class Writer:
            def __init__(self): self.sent = b""
            def write(self, data): self.sent += data
            async def drain(self): await clock.sleep(1.5)
        writer = Writer()
        connection = transport.TcpConnection(None, writer, clock=clock)
        task = asyncio.create_task(connection.send(b"x" * 8193))
        for _ in range(10): await asyncio.sleep(0)
        clock.advance(1.5)
        for _ in range(10): await asyncio.sleep(0)
        clock.advance(.6)
        for _ in range(10): await asyncio.sleep(0)
        with self.assertRaises(TimeoutError): await task
        self.assertEqual(len(writer.sent), 8192)

    async def test_shared_imports_do_not_load_simulator_or_test_packages(self):
        self.modules()
        import subprocess
        import sys
        result = subprocess.run([sys.executable, "-c",
            "import sys; import synqaro_protocol.codec, synqaro_protocol.transport; "
            "assert 'simquaro' not in sys.modules; assert 'tests' not in sys.modules"],
            capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)

    async def test_connect_timeout_closes_late_completion(self):
        transport, _ = self.modules()
        from unittest.mock import patch
        from tests.simquaro.support.clock import VirtualClock
        clock = VirtualClock()
        class Writer:
            closed = False
            def close(self): self.closed = True
            async def wait_closed(self): pass
        writer = Writer()
        async def late(*args, **kwargs):
            try:
                await clock.sleep(10)
            except asyncio.CancelledError:
                return object(), writer
        with patch("asyncio.open_connection", late):
            task = asyncio.create_task(transport.TcpConnection.open("ignored", 1, clock=clock))
            for _ in range(10): await asyncio.sleep(0)
            clock.advance(2.1)
            for _ in range(10): await asyncio.sleep(0)
            with self.assertRaises(TimeoutError): await task
        self.assertTrue(writer.closed)
