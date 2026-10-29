"""Wire injections act on real TCP deliveries after model execution."""

import asyncio
from unittest.mock import AsyncMock, patch

from tests.simquaro.test_server import RawSessionCase, turns


class WireFaultTests(RawSessionCase):
    async def test_dropped_setting_keeps_verified_physical_effect(self):
        self.faults.schedule("drop_response", when="frequency_set_verified")
        r, w = await self.connect()
        w.write(b"#set <id=1>: name=frequency, value=6, unit=GHz\n")
        await self.tick(.1)
        w.write(b"#get <id=2>: name=frequency\n")
        reply = await self.line(r)
        self.assertIn(b"#ok <id=2>: name=frequency, value=6", reply)

    async def test_delayed_reply_does_not_hold_writer_and_arrives_late(self):
        self.faults.schedule("delay_response", when="response_ready", parameters={"delay_ms": 2500})
        r, w = await self.connect()
        w.write(b"#status <id=1>\n#status <id=2>\n")
        self.assertIn(b"#ok <id=2>", await self.line(r))
        await self.tick(2.001)
        self.assertEqual(self.server.sessions[0].pending_count, 1)
        await self.tick(.499)
        self.assertIn(b"#ok <id=1>", await self.line(r))

    async def test_malformed_response_retains_id_and_omit_lf_is_exact(self):
        self.faults.schedule("malformed_response", when="response_ready")
        self.faults.schedule("omit_lf", when="response_ready")
        r, w = await self.connect()
        w.write(b"#get <id=1>: name=frequency\n")
        reply = await asyncio.wait_for(r.read(4096), 1)
        self.assertIn(b"<id=1>", reply)
        self.assertNotIn(b"\n", reply)
        self.assertNotIn(b": name=", reply)

    async def test_reorder_final_occurrence_waits_next_matching_trigger(self):
        self.faults.schedule("reorder_responses", when="frequency_set_verified")
        r, w = await self.connect()
        w.write(b"#set <id=1>: name=frequency, value=6, unit=GHz\n")
        await self.tick(.1)
        self.assertEqual(self.faults.snapshot()["rules"], [])
        w.write(b"#status <id=2>\n")
        self.assertIn(b"#ok <id=2>", await self.line(r))
        await turns()
        self.assertEqual(self.server.sessions[0].pending_count, 1)
        w.write(b"#set <id=3>: name=frequency, value=7, unit=GHz\n")
        await self.tick(.1)
        self.assertIn(b"#ok <id=3>", await self.line(r))
        self.assertIn(b"#ok <id=1>", await self.line(r))

    async def test_reorder_timeout_releases_after_two_seconds(self):
        self.faults.schedule("reorder_responses", when="response_ready")
        r, w = await self.connect()
        w.write(b"#status <id=1>\n")
        await self.tick(2)
        self.assertIn(b"#ok <id=1>", await self.line(r))

    async def test_rejection_diagnostic_obeys_reorder_timeout_without_extra_requests(self):
        self.faults.schedule("reorder_responses", when="response_ready")
        r, w = await self.connect()
        w.write(b"#status\n")
        reply = asyncio.create_task(r.readline())
        self.addAsyncCleanup(self._cancel_read, reply)
        await turns()
        self.assertFalse(reply.done(), "reorder must also affect a diagnostic reply")
        await self.tick(2)
        self.assertEqual(await asyncio.wait_for(reply, 1), b"#error: code=INVALID_ID\n")

    async def _cancel_read(self, task):
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def test_disconnect_after_setting_keeps_action(self):
        self.faults.schedule("disconnect", when="frequency_set_verified")
        r, w = await self.connect()
        with self.assertLogs("simquaro.session", "INFO") as logs:
            w.write(b"#set <id=1>: name=frequency, value=6, unit=GHz\n")
            await self.tick(.1)
            self.assertEqual(await self.line(r), b"")
        self.assertIn("wire dropped", " ".join(logs.output))
        self.assertEqual(self.model.snapshot()["actual"]["frequency"], "6")

    async def test_lost_reboot_acceptance_still_reboots(self):
        self.faults.schedule("drop_response", when="response_ready")
        old = self.model.boot_id
        r, w = await self.connect()
        with self.assertLogs("simquaro.server", "WARNING"):
            w.write(b"#reboot <id=1>\n")
            self.assertEqual(await self.line(r), b"")
            await turns(100)
        self.assertNotEqual(old, self.model.boot_id)

    async def test_reboot_delay_cannot_extend_one_second_transmission_budget(self):
        self.faults.schedule("delay_response", when="response_ready", parameters={"delay_ms": 60000})
        old = self.model.boot_id
        r, w = await self.connect()
        with self.assertLogs("simquaro.server", "WARNING"):
            w.write(b"#reboot <id=1>\n")
            await self.tick(1.001)
            self.assertEqual(await self.line(r), b"")
            await turns(100)
        self.assertNotEqual(old, self.model.boot_id)

    async def test_multiple_reordered_frames_are_whole_and_bounded(self):
        self.faults.schedule("reorder_responses", when="response_ready", times=4)
        r, w = await self.connect()
        w.write(b"".join(f"#get <id={n}>: name=configuration\n".encode() for n in range(1, 5)))
        replies = [await self.line(r) for _ in range(4)]
        ids = [int(line.split(b"id=")[1].split(b">")[0]) for line in replies]
        self.assertEqual(set(ids), {1, 2, 3, 4})
        self.assertLess(ids.index(2), ids.index(1))
        self.assertLess(ids.index(4), ids.index(3))
        for reply in replies:
            self.assertEqual(reply.count(b"#ok"), 1)
            self.assertTrue(reply.endswith(b"\n"))
            self.assertLessEqual(len(reply), 4096)

    async def test_reboot_queue_deadline_is_shared_one_second(self):
        old = self.model.boot_id
        r, w = await self.connect()
        with patch("simquaro.server._outgoing_bytes", return_value=1):
            with self.assertLogs("simquaro.server", "WARNING"):
                w.write(b"#reboot <id=1>\n")
                self.assertEqual(await self.line(r), b"#accepted <id=1>\n")
                await self.tick(1.001)
                self.assertEqual(await self.line(r), b"")
                await turns(100)
        self.assertNotEqual(old, self.model.boot_id)

    async def test_reboot_drain_failure_still_restarts(self):
        old = self.model.boot_id
        r, w = await self.connect()
        await turns()
        session = self.server.sessions[0]
        with patch.object(session.writer, "drain", new=AsyncMock(side_effect=ConnectionResetError("lost transport"))):
            with self.assertLogs("simquaro.server", "WARNING"):
                w.write(b"#reboot <id=1>\n")
                self.assertEqual(await self.line(r), b"#accepted <id=1>\n")
                self.assertEqual(await self.line(r), b"")
                await turns(100)
        self.assertNotEqual(old, self.model.boot_id)
