"""Configuration changes are saved separately from verified process application."""

import asyncio
from contextlib import redirect_stdout, redirect_stderr
from dataclasses import replace
import importlib
import io
import json
from pathlib import Path
import tempfile
import socket
import signal
import sys
import unittest

from simquaro.cli import main
from simquaro.configuration import ConfigStore, InventoryEntry
from simquaro.runtime import Runtime


class ConfigurationCliTests(unittest.TestCase):
    def test_invalid_explicit_file_actions_retain_its_path(self):
        with tempfile.TemporaryDirectory(prefix="sq-config-actions-") as directory:
            path = Path(directory) / "missing inventory.json"
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                code = main(["--json", "--config", str(path), "list"])
            self.assertEqual(code, 1)
            actions = json.loads(out.getvalue())["error"]["actions"]
            self.assertEqual(actions[0][:3], ["simquaro", "--config", str(path)])

    def test_explicit_path_init_show_validate_and_injected_inventory_conflict(self):
        with tempfile.TemporaryDirectory(prefix="sq-config-cli-") as directory:
            path = Path(directory) / "instances.json"
            for arguments in (["config", "init"], ["config", "show"], ["config", "validate"]):
                out, err = io.StringIO(), io.StringIO()
                with redirect_stdout(out), redirect_stderr(err):
                    code = main(["--json", "--config", str(path), *arguments])
                self.assertEqual(code, 0, err.getvalue())
                self.assertTrue(json.loads(out.getvalue())["ok"])
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(main(["--config", str(path), "list"], inventory={}), 2)


class ConfigurationApplyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        module = importlib.import_module("simquaro.configuration")
        self.assertTrue(hasattr(module, "ConfigurationService"), "configuration apply service is missing")
        self.temp = tempfile.TemporaryDirectory(prefix="sq-apply-")
        self.addCleanup(self.temp.cleanup)
        self.store = ConfigStore(Path(self.temp.name) / "instances.json")
        self.snapshot = self.store.initialize()
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        entry = self.snapshot.entries["receiver-a"]
        self.snapshot = self.store.save({"receiver-a": replace(entry, config=replace(entry.config, port=port))},
                                        expected_revision=self.snapshot.revision)
        self.runtime = Runtime(Path(self.temp.name) / "run")
        self.service = module.ConfigurationService(self.store, self.runtime)
        self.addAsyncCleanup(self.runtime.stop, "receiver-a")
        self.children = []
        async def reap():
            for child in self.children:
                if child.returncode is None: await child.terminate()
                await child.wait()
        self.addAsyncCleanup(reap)

    async def test_save_does_not_restart_and_apply_returns_child_ownership(self):
        first = await self.service.apply("receiver-a", expected_revision=self.snapshot.revision)
        self.assertTrue(first.outcome["ok"], first.outcome)
        self.children.append(first.started.child)
        original = await self.runtime.inspect(self.snapshot.entries["receiver-a"].config)
        entry = self.snapshot.entries["receiver-a"]
        edited = replace(entry, config=replace(entry.config, settings=replace(entry.config.settings, initial_frequency=6)))
        fresh = self.store.save({"receiver-a": edited}, expected_revision=self.snapshot.revision)
        status = await self.service.inspect("receiver-a")
        self.assertTrue(status["pending"])
        self.assertEqual(status["active"]["receiver"]["initial_frequency"], 5)
        still = await self.runtime.inspect(edited.config)
        self.assertEqual(still["status"]["run_token"], original["status"]["run_token"])
        second = await self.service.apply("receiver-a", expected_revision=fresh.revision)
        self.children.append(second.started.child)
        self.assertTrue(second.outcome["ok"], second.outcome)
        status = await self.service.inspect("receiver-a")
        self.assertFalse(status["pending"])
        self.assertEqual(status["active"]["receiver"]["initial_frequency"], 6)

    async def test_hardware_apply_rejected_before_runtime(self):
        entry = self.snapshot.entries["receiver-a"]
        fresh = self.store.save({"receiver-a": InventoryEntry(entry.config, "hardware")},
                                expected_revision=self.snapshot.revision)
        from simquaro.configuration import ConfigurationError
        with self.assertRaises(ConfigurationError) as caught:
            await self.service.apply("receiver-a", expected_revision=fresh.revision)
        self.assertEqual(caught.exception.code, "FORBIDDEN_TARGET_KIND")
        self.assertFalse((self.runtime.root / "receiver-a.json").exists())

    async def test_apply_transfers_child_before_fallible_followup_inspection(self):
        from unittest.mock import patch
        # A follow-up query must not lose the newly created process handle.
        with patch.object(self.runtime, "inspect", side_effect=RuntimeError("inspection unavailable")):
            result = await self.service.apply("receiver-a", expected_revision=self.snapshot.revision)
        self.children.append(result.started.child)
        self.assertTrue(result.outcome["ok"])
        self.assertEqual(result.outcome["requested_revision"], self.snapshot.revision)
        self.assertEqual(result.outcome["startup_config"]["receiver"]["initial_frequency"], 5)

    async def test_failed_apply_keeps_saved_values_and_reports_stopped_not_rollback(self):
        first = await self.service.apply("receiver-a", expected_revision=self.snapshot.revision)
        self.children.append(first.started.child)
        entry = self.snapshot.entries["receiver-a"]
        with socket.socket() as busy:
            busy.bind(("127.0.0.1", 0))
            busy.listen()
            port = busy.getsockname()[1]
            saved = self.store.save({"receiver-a": replace(entry, config=replace(entry.config, port=port))},
                                    expected_revision=self.snapshot.revision)
            result = await self.service.apply("receiver-a", expected_revision=saved.revision)
        self.assertFalse(result.outcome["ok"])
        self.assertEqual(self.store.load().entries["receiver-a"].config.port, port)
        self.assertEqual((await self.service.inspect("receiver-a"))["state"], "stopped")

    async def test_concurrent_start_cannot_interleave_between_restart_stop_and_start(self):
        from unittest.mock import patch
        first = await self.service.apply("receiver-a", expected_revision=self.snapshot.revision)
        self.children.append(first.started.child)
        config = self.snapshot.entries["receiver-a"].config
        changed = replace(config, settings=replace(config.settings, initial_frequency=6))
        stopped, resume = asyncio.Event(), asyncio.Event()
        original = self.runtime._stop_locked
        async def hold(directory, name, **kwargs):
            result = await original(directory, name, **kwargs)
            stopped.set()
            await resume.wait()
            return result
        with patch.object(self.runtime, "_stop_locked", new=hold):
            restart = asyncio.create_task(self.runtime.restart(changed))
            self.addCleanup(resume.set)
            await asyncio.wait_for(stopped.wait(), 3)
            competing = asyncio.create_task(self.runtime.start(config))
            await asyncio.sleep(.02)
            self.assertFalse(competing.done())
            resume.set()
            restarted, other = await asyncio.gather(restart, competing)
            self.children.append(restarted.child)
        self.assertEqual(other.outcome["outcome"], "already_running")
        self.assertEqual(other.outcome["startup_config"]["receiver"]["initial_frequency"], 6)

    async def test_start_all_skips_physical_targets(self):
        entry = self.snapshot.entries["receiver-a"]
        physical = InventoryEntry(replace(entry.config, name="physical-b", port=1), "hardware")
        self.store.save({"receiver-a": entry, "physical-b": physical}, expected_revision=self.snapshot.revision)
        script = ("from pathlib import Path; from simquaro.cli import main; "
            f"raise SystemExit(main(['--json','--config',{str(self.store.path)!r},'start','all'],"
            f"runtime_root=Path({str(self.runtime.root)!r})))")
        process = await asyncio.create_subprocess_exec(sys.executable, "-c", script,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            skipped = json.loads(await asyncio.wait_for(process.stdout.readline(), 3))
            self.assertEqual(skipped["event"], "selection.skipped")
            self.assertEqual(skipped["result"]["targets"], ["physical-b"])
            started = json.loads(await asyncio.wait_for(process.stdout.readline(), 3))
            self.assertEqual(started["instance"], "receiver-a")
            self.assertFalse((self.runtime.root / "physical-b.json").exists())
            process.send_signal(signal.SIGINT)
            await asyncio.wait_for(process.communicate(), 5)
            self.assertEqual(process.returncode, 0)
        finally:
            if process.returncode is None: process.kill()
            await process.wait()
