"""The manual console sends diagnostic bytes, not corrected protocol messages."""

import asyncio
import importlib
import json
import os
import signal
import sys
import unittest


class ConsoleEncodingTests(unittest.TestCase):
    def module(self):
        try: return importlib.import_module("simquaro.console")
        except ImportError: self.fail("manual console is missing")

    def test_raw_notation_and_safe_reversible_display(self):
        console = self.module()
        wire = b"text\x00\xff\r\n\t\\\x1b[31m"
        self.assertEqual(console.decode_raw(r"text\x00\xFF\r\n\t\\\x1b[31m"), wire)
        self.assertEqual(console.decode_raw(console.render_bytes(wire)), wire)
        self.assertNotIn("\x1b", console.render_bytes(wire))
        self.assertEqual(console.decode_raw("#status <id=1>"), b"#status <id=1>")

    def test_invalid_notation_and_submission_limits(self):
        console = self.module()
        for text in (r"bad\q", r"bad\xF", "trailing\\", "nonascii-è", "a" * 65537):
            with self.subTest(text=text[:20]), self.assertRaises(ValueError):
                console.decode_raw(text)
        self.assertEqual(len(console.decode_raw("a" * 4097)), 4097)
        self.assertEqual(len(console.decode_raw(r"\xFF" * 65536)), 65536)


class ConsoleWireTests(unittest.IsolatedAsyncioTestCase):
    async def console(self, raw=False, reply_on_eof=False):
        try: importlib.import_module("simquaro.console")
        except ImportError: self.fail("manual console is missing")
        self.frames = []
        self.readers = []
        async def peer(reader, writer):
            self.readers.append(reader)
            try:
                while data := await reader.read(4096):
                    self.frames.append(data)
                    if b"close" in data:
                        writer.write(b"part\x1b[31m\xff\n")
                        await writer.drain()
                        break
                else:
                    if reply_on_eof:
                        writer.write(b"after-eof\n")
                        await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()
        server = await asyncio.start_server(peer, "127.0.0.1", 0)
        self.addAsyncCleanup(server.wait_closed)
        self.addCleanup(server.close)
        port = server.sockets[0].getsockname()[1]
        script = ("from simquaro.cli import main; from simquaro.config import InstanceConfig; "
                  f"raise SystemExit(main(['--json','console','receiver-a']+{['--raw'] if raw else []!r}, "
                  f"inventory={{'receiver-a':InstanceConfig('receiver-a','fictitious_receiver','127.0.0.1',{port})}}))")
        process = await asyncio.create_subprocess_exec(sys.executable, "-c", script,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE)
        async def cleanup():
            if process.returncode is None:
                process.kill()
            await process.wait()
        self.addAsyncCleanup(cleanup)
        connected = json.loads(await asyncio.wait_for(process.stdout.readline(), 3))
        self.assertEqual(connected["event"], "console.connected")
        return process

    async def test_line_mode_remote_eof_ends_even_with_stdin_open(self):
        process = await self.console()
        process.stdin.write(b"close nonsense\n")
        await process.stdin.drain()
        await asyncio.wait_for(process.wait(), 3)  # stdin is intentionally still open.
        stdout, stderr = await asyncio.wait_for(process.communicate(), 3)
        self.assertEqual(process.returncode, 0, stderr)
        self.assertEqual(b"".join(self.frames), b"close nonsense\n")
        records = [json.loads(line) for line in stdout.splitlines()]
        rx = next(record for record in records if record["event"] == "console.rx")
        self.assertEqual(rx["result"]["data"], r"part\x1b[31m\xFF\n")

    async def test_raw_invalid_escape_sends_nothing_and_has_no_hidden_requests(self):
        process = await self.console(raw=True)
        process.stdin.write(b"bad\\q\nclose\\x00\\xFF\n")
        await process.stdin.drain()
        stdout, stderr = await asyncio.wait_for(process.communicate(), 3)
        self.assertEqual(process.returncode, 0, stderr)
        self.assertEqual(b"".join(self.frames), b"close\x00\xff")
        self.assertTrue(any(json.loads(line)["event"] == "console.error" for line in stdout.splitlines()))

    async def test_no_data_notice_does_not_close_or_send_a_probe(self):
        process = await self.console(raw=True)
        process.stdin.write(b"incomplete\n")
        await process.stdin.drain()
        tx = json.loads(await asyncio.wait_for(process.stdout.readline(), 1))
        self.assertEqual(tx["event"], "console.tx")
        notice = json.loads(await asyncio.wait_for(process.stdout.readline(), 3))
        self.assertEqual(notice["event"], "console.observation")
        self.assertIsNone(process.returncode)
        self.assertEqual(b"".join(self.frames), b"incomplete")

    async def test_piped_input_half_close_allows_reply_and_oversized_wire(self):
        process = await self.console(raw=True, reply_on_eof=True)
        stdout, stderr = await asyncio.wait_for(process.communicate(b"x" * 4097 + b"\n"), 3)
        self.assertEqual(process.returncode, 0, stderr)
        self.assertEqual(b"".join(self.frames), b"x" * 4097)
        records = [json.loads(line) for line in stdout.splitlines()]
        self.assertTrue(any(r["event"] == "console.rx" and r["result"]["data"] == r"after-eof\n"
                            for r in records))

    async def test_ctrl_c_closes_promptly(self):
        process = await self.console()
        process.send_signal(signal.SIGINT)
        await asyncio.wait_for(process.wait(), 3)
        self.assertEqual(process.returncode, 130)
