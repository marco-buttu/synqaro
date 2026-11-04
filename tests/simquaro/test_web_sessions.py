"""GUI services use real TCP; HTTP and browser packages are not required."""

import asyncio
from dataclasses import replace
import importlib
from pathlib import Path
import tempfile
import unittest

from simquaro.configuration import ConfigStore
from tests.simquaro.support.clock import VirtualClock
from tests.simquaro.test_conformance import ScriptedClientCase
from tests.simquaro.test_server import turns


class SessionTests(ScriptedClientCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.temp = tempfile.TemporaryDirectory(prefix="sq-sessions-")
        self.addCleanup(self.temp.cleanup)
        self.store = ConfigStore(Path(self.temp.name) / "instances.json")
        snapshot = self.store.initialize()
        entry = snapshot.entries["receiver-a"]
        self.snapshot = self.store.save({"receiver-a": replace(entry, config=replace(entry.config,
            host=self.address[0], port=self.address[1]))}, expected_revision=snapshot.revision)
        try:
            module = importlib.import_module("simquaro.web.sessions")
        except ImportError:
            self.fail("GUI session service is missing")
        self.manager = module.SessionManager(self.store, clock=self.clock)
        self.addAsyncCleanup(self.manager.close)

    async def asyncTearDown(self):
        if hasattr(self, "manager"): await self.manager.close()
        await super().asyncTearDown()

    async def test_raw_connect_sends_nothing_and_each_tab_has_its_own_connection(self):
        a = await self.manager.connect("receiver-a", "raw")
        b = await self.manager.connect("receiver-a", "raw")
        await turns(20)
        self.assertEqual(self.connections, 2)
        self.assertEqual(self.frames, [])
        await self.manager.submit(a["id"], {"text": r"#status <id=19>\n"})
        await turns(50)
        self.assertEqual(self.frames, [(1, b"#status <id=19>\n")])
        events = self.manager.events(a["id"], 0)["events"]
        self.assertIn(r"#status <id=19>\n", [e.get("data") for e in events if e["kind"] == "tx"])
        self.assertFalse(any(e["kind"] == "rx" for e in self.manager.events(b["id"], 0)["events"]))

    async def test_managed_wire_evidence_and_numbers_preserve_spelling(self):
        a = await asyncio.wait_for(self.manager.connect("receiver-a", "managed"), 3)
        result = await asyncio.wait_for(self.manager.submit(a["id"], {"verb": "set", "fields": {
            "name": "frequency", "value": {"number": "5.1234565"}, "unit": "GHz"}}), 3)
        self.assertEqual(result["verb"], "ok")
        self.assertEqual(self.frames[-1][1], b'#set <id=3>: name="frequency", value=5.1234565, unit="GHz"\n')
        events = self.manager.events(a["id"], 0)["events"]
        self.assertIn(r'#status <id=2>\n', [e["data"] for e in events if e["kind"] == "tx"])
        with self.assertRaises(ValueError):
            await self.manager.submit(a["id"], {"verb": "set", "fields": {"value": 5.1}})

    async def test_sessions_pin_saved_settings_and_new_connections_see_new_revision(self):
        a = await self.manager.connect("receiver-a", "raw")
        entry = self.snapshot.entries["receiver-a"]
        edited = replace(entry, config=replace(entry.config, settings=replace(entry.config.settings, initial_frequency=6)))
        fresh = self.store.save({"receiver-a": edited}, expected_revision=self.snapshot.revision)
        b = await self.manager.connect("receiver-a", "raw")
        self.assertEqual(a["revision"], self.snapshot.revision)
        self.assertEqual(b["revision"], fresh.revision)
        self.assertEqual(self.manager.events(a["id"], 0)["revision"], self.snapshot.revision)

    async def test_caps_event_gaps_and_expired_lease_close_tcp_without_firmware_cancel(self):
        sessions = [await self.manager.connect("receiver-a", "raw") for _ in range(4)]
        with self.assertRaises(ValueError) as caught:
            await self.manager.connect("receiver-a", "raw")
        self.assertEqual(caught.exception.code, "SESSION_LIMIT")
        sid = sessions[0]["id"]
        for _ in range(260):
            await self.manager.submit(sid, {"text": ""})
        history = self.manager.events(sid, 0)
        self.assertTrue(history["gap"])
        self.assertLessEqual(len(history["events"]), 256)
        self.clock.advance(121)
        await turns(60)
        await self.manager.expire()
        with self.assertRaises(ValueError): self.manager.events(sid, 0)
        self.assertFalse(any(b"cancel" in frame for _, frame in self.frames))
        self.assertTrue(all(writer.is_closing() for writer in self.writers))

    async def test_raw_local_no_data_notice_does_not_probe_or_disconnect(self):
        a = await self.manager.connect("receiver-a", "raw")
        await self.manager.submit(a["id"], {"text": ""})
        await turns(20)
        self.clock.advance(2.1)
        await turns(40)
        history = self.manager.events(a["id"], 0)
        self.assertEqual(history["state"], "connected")
        self.assertIn("observation", [e["kind"] for e in history["events"]])
        self.assertEqual(self.frames, [])


class JobTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        try: self.module = importlib.import_module("simquaro.web.jobs")
        except ImportError: self.fail("GUI job service is missing")
        self.jobs = self.module.JobManager()
        self.addAsyncCleanup(self.jobs.close)

    async def test_job_runs_once_polling_never_reexecutes_and_shutdown_joins(self):
        count = []
        async def operation():
            count.append(1)
            return {"answer": 42}
        jid = self.jobs.start("test", "receiver-a", operation())
        await turns(10)
        for _ in range(10): self.assertEqual(self.jobs.get(jid)["state"], "succeeded")
        self.assertEqual(count, [1])
        joined = asyncio.Event()
        async def unfinished():
            try: await asyncio.Event().wait()
            finally: joined.set()
        pending = self.jobs.start("test", "other", unfinished())
        await turns(10)
        await self.jobs.close()
        self.assertTrue(joined.is_set())
        self.assertEqual(self.jobs.get(pending)["state"], "interrupted")

    async def test_target_busy_and_active_and_completed_caps(self):
        async def wait(): await asyncio.Event().wait()
        first = self.jobs.start("test", "receiver-a", wait())
        self.assertTrue(self.jobs.busy("receiver-a"))
        for n in range(15): self.jobs.start("test", str(n), wait())
        with self.assertRaises(ValueError) as caught: self.jobs.start("test", "over", wait())
        self.assertEqual(caught.exception.code, "JOB_LIMIT")
        await self.jobs.close()
        self.assertEqual(self.jobs.get(first)["state"], "interrupted")

    async def test_shutdown_stops_only_server_created_children(self):
        import socket
        from simquaro.instances import builtin_inventory
        from simquaro.runtime import Runtime
        with tempfile.TemporaryDirectory(prefix="sq-job-ownership-") as directory:
            runtime = Runtime(Path(directory) / "run")
            configs = []
            for name in ("external-a", "owned-b"):
                with socket.socket() as sock:
                    sock.bind(("127.0.0.1", 0))
                    configs.append(replace(builtin_inventory()["receiver-a"], name=name, port=sock.getsockname()[1]))
            external, owned = [await runtime.start(config) for config in configs]
            try:
                self.assertTrue(external.outcome["ok"])
                self.assertTrue(owned.outcome["ok"])
                # Discovery of an existing instance must not transfer ownership.
                self.jobs.own(runtime, await runtime.start(configs[0]))
                self.jobs.own(runtime, owned)
                await self.jobs.close()
                self.assertEqual((await runtime.inspect(configs[0]))["outcome"], "running")
                self.assertEqual((await runtime.inspect(configs[1]))["outcome"], "stopped")
            finally:
                for config in configs: await runtime.stop(config.name)
                for started in (external, owned):
                    if started.child is not None: await started.child.wait()
