"""Lifecycle tests use only children and private paths created by this suite."""

import asyncio
from dataclasses import replace
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from simquaro.config import InstanceConfig, ReceiverConfig
from simquaro.control import control_request
from simquaro.faults import FaultEffect, FaultRule, Scenario

if importlib.util.find_spec("simquaro.runtime"):
    from simquaro.runtime import Runtime
else:
    Runtime = None


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.assertIsNotNone(Runtime, "safe process runtime is missing")
        self.temp = tempfile.TemporaryDirectory(prefix="sq-")
        self.root = Path(self.temp.name) / "run"
        self.runtime = Runtime(self.root)
        self.log = tempfile.TemporaryFile()
        self.saved_stderr = os.dup(2)
        os.dup2(self.log.fileno(), 2)
        self.results = []
        self.helpers = []
        self.config = InstanceConfig("receiver-a", "fictitious_receiver", "127.0.0.1", 0)

    async def asyncTearDown(self):
        for result in self.results:
            if result.child is not None and result.child.returncode is None:
                # Direct handles here belong to this test, never arbitrary PIDs.
                result.child.signal(signal.SIGKILL)
                await result.child.wait()
        for process in self.helpers:
            if process.returncode is None:
                process.kill()
            await process.wait()
        os.dup2(self.saved_stderr, 2)
        os.close(self.saved_stderr)
        self.log.close()
        self.temp.cleanup()

    async def start(self, config=None, scenario=Scenario(), runtime=None):
        result = await (runtime or self.runtime).start(config or self.config, scenario=scenario)
        self.results.append(result)
        return result

    def metadata(self, name="receiver-a"):
        return self.root / f"{name}.json"

    async def helper(self, mode, name="receiver-a"):
        process = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "tests.simquaro.support.processes", mode,
            str(self.root), name, stdout=asyncio.subprocess.PIPE)
        self.helpers.append(process)
        self.assertEqual(await asyncio.wait_for(process.stdout.readline(), 3), b"ready\n")
        return process

    async def test_lock_file_existence_does_not_mean_running(self):
        self.root.joinpath("receiver-a.lock").touch(mode=0o600)
        result = await self.start()
        self.assertTrue(result.outcome["ok"], result.outcome)
        self.assertEqual(result.outcome["outcome"], "started")
        stopped = await self.runtime.stop("receiver-a")
        self.assertTrue(stopped["ok"], stopped)
        self.assertTrue(self.root.joinpath("receiver-a.lock").exists())
        self.assertFalse(self.metadata().exists())
        self.assertFalse(self.root.joinpath("receiver-a.sock").exists())
        self.assertTrue((await self.runtime.stop("receiver-a"))["ok"])

    async def test_held_lock_without_metadata_is_not_stale(self):
        fd = os.open(self.root / "receiver-a.lock", os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = await self.start()
            self.assertFalse(result.outcome["ok"])
            self.assertIsNone(result.child)
            self.assertIn("error", result.outcome)
        finally:
            os.close(fd)

    async def test_readiness_does_not_consume_faults_or_assert_health(self):
        scenario = Scenario((FaultEffect("synthesizer_failure"),),
                            (FaultRule("drop_response", "response_ready"),))
        result = await self.start(scenario=scenario)
        self.assertTrue(result.outcome["ok"], result.outcome)
        status = result.outcome["status"]
        self.assertEqual(status["runtime"]["hardware_listener"], "listening")
        self.assertFalse(status["runtime"]["hardware_communication_verified"])
        self.assertEqual(status["faults"]["rules"][0]["remaining"], 1)
        self.assertEqual(status["model"]["reported"]["general"]["health"], "fault")
        again = await self.runtime.inspect(self.config)
        self.assertEqual(again["status"]["faults"]["rules"][0]["remaining"], 1)

    async def test_existing_instance_not_reconfigured_or_owned(self):
        first = await self.start()
        changed = replace(self.config, receiver=ReceiverConfig(initial_frequency=7))
        second = await self.start(changed, scenario=Scenario((FaultEffect("clock_untrusted"),)))
        self.assertTrue(second.outcome["ok"], second.outcome)
        self.assertEqual(second.outcome["outcome"], "already_running")
        self.assertIsNone(second.child)
        self.assertEqual(second.outcome["startup_config"]["receiver"]["initial_frequency"], 5)
        self.assertEqual(second.outcome["configured"]["receiver"]["initial_frequency"], 7)
        self.assertEqual(second.outcome["status"]["run_token"], first.outcome["status"]["run_token"])

    async def test_concurrent_starts_create_one_child(self):
        first, second = await asyncio.gather(self.start(), self.start(runtime=Runtime(self.root)))
        self.assertEqual(sorted(r.outcome["outcome"] for r in (first, second)),
                         ["already_running", "started"])
        self.assertEqual(sum(r.child is not None for r in (first, second)), 1)

    async def test_crash_socket_recovered_without_deleting_lock(self):
        first = await self.start()
        lock_inode = (self.root / "receiver-a.lock").stat().st_ino
        first.child.signal(signal.SIGKILL)
        await first.child.wait()
        self.assertTrue((self.root / "receiver-a.sock").exists())
        second = await self.start()
        self.assertTrue(second.outcome["ok"], second.outcome)
        self.assertNotEqual(first.outcome["status"]["run_token"], second.outcome["status"]["run_token"])
        self.assertEqual((self.root / "receiver-a.lock").stat().st_ino, lock_inode)

    async def test_pid_birth_mismatch_refuses_to_signal_owned_child(self):
        result = await self.start()
        data = json.loads(self.metadata().read_text())
        data["birth"] += 1
        self.metadata().write_text(json.dumps(data))
        stopped = await self.runtime.stop("receiver-a")
        self.assertFalse(stopped["ok"])
        self.assertEqual(stopped["error"]["code"], "IDENTITY_MISMATCH")
        self.assertIsNone(result.child.returncode)
        self.assertTrue(self.metadata().exists())

    async def test_replaced_socket_preserved(self):
        result = await self.start()
        path = self.root / "receiver-a.sock"
        path.unlink()
        other = socket.socket(socket.AF_UNIX)
        self.addCleanup(other.close)
        other.bind(str(path))
        inode = path.stat().st_ino
        stopped = await self.runtime.stop("receiver-a")
        self.assertFalse(stopped["ok"])
        self.assertEqual(path.stat().st_ino, inode)
        # Refusing before signaling also avoids treating an alien endpoint as ours.
        self.assertIsNone(result.child.returncode)

    async def test_live_unresponsive_control_is_not_dead(self):
        child = await self.helper("resistant")
        result = await self.start()
        self.assertFalse(result.outcome["ok"])
        self.assertEqual(result.outcome["error"]["code"], "CONTROL_UNRESPONSIVE")
        self.assertIsNone(result.child)
        self.assertIsNone(child.returncode)
        self.assertIn(["simquaro", "restart", "receiver-a"], result.outcome["error"]["actions"])

    async def test_stop_escalates_resistant_child_only_and_verifies_exit(self):
        unrelated = await self.helper("sentinel", "unrelated")
        resistant = await self.helper("resistant")
        stopped = await self.runtime.stop("receiver-a")
        self.assertTrue(stopped["ok"], stopped)
        self.assertTrue(stopped["escalated"])
        self.assertTrue((self.root / "receiver-a.term-seen").exists())
        self.assertEqual(await asyncio.wait_for(resistant.wait(), 1), -signal.SIGKILL)
        self.assertIsNone(unrelated.returncode)
        self.assertTrue((await self.runtime.stop("receiver-a"))["ok"])
        self.assertIsNone(unrelated.returncode)

    async def test_graceful_child_exits_without_escalation(self):
        child = await self.helper("graceful")
        stopped = await self.runtime.stop("receiver-a")
        self.assertTrue(stopped["ok"], stopped)
        self.assertFalse(stopped["escalated"])
        self.assertEqual(await child.wait(), 0)

    async def test_occupied_tcp_port_does_not_leave_worker_or_state(self):
        busy = socket.socket()
        self.addCleanup(busy.close)
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        result = await self.start(replace(self.config, port=busy.getsockname()[1]))
        self.assertFalse(result.outcome["ok"])
        if result.child:
            self.assertIsNotNone(result.child.returncode)
        self.assertFalse(self.metadata().exists())
        self.assertFalse((self.root / "receiver-a.sock").exists())

    async def test_restart_applies_initial_scenario_and_new_firmware(self):
        first = await self.start()
        await control_request(self.root / "receiver-a.sock", "fault.activate", {"name": "clock_untrusted"})
        restarted = await self.runtime.restart(self.config)
        self.results.append(restarted)
        self.assertTrue(restarted.outcome["ok"], restarted.outcome)
        self.assertNotEqual(restarted.outcome["status"]["run_token"], first.outcome["status"]["run_token"])
        self.assertEqual(restarted.outcome["status"]["faults"]["active"], [])

    async def test_foreground_cancel_stops_only_newly_owned_children(self):
        existing = await self.start(replace(self.config, name="receiver-b"))
        adopted = await self.start(replace(self.config, name="receiver-b"))
        owned = await self.start()
        task = asyncio.create_task(self.runtime.supervise([adopted, owned]))
        await asyncio.sleep(0)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertIsNotNone(owned.child.returncode)
        self.assertIsNone(existing.child.returncode)

    async def test_supervision_reports_child_failure_without_stopping_another(self):
        first = await self.start()
        second = await self.start(replace(self.config, name="receiver-b"))
        task = asyncio.create_task(self.runtime.supervise([first, second]))
        first.child.signal(signal.SIGKILL)
        await first.child.wait()
        await asyncio.sleep(.05)
        self.assertFalse(task.done())
        self.assertIsNone(second.child.returncode)
        await self.runtime.stop("receiver-b")
        self.assertEqual(await asyncio.wait_for(task, 2), 1)

    async def test_old_parent_cleanup_does_not_stop_replacement(self):
        old = await self.start()
        await self.runtime.stop("receiver-a")
        new = await self.start(runtime=Runtime(self.root))
        self.assertEqual(await self.runtime.supervise([old]), 0)
        self.assertIsNone(new.child.returncode)
        self.assertEqual((await self.runtime.inspect(self.config))["status"]["run_token"],
                         new.outcome["status"]["run_token"])

    async def test_ownership_descriptors_not_inherited_by_unrelated_subprocess(self):
        first = await self.start()
        unrelated = await self.helper("sentinel", "unrelated")
        await self.runtime.stop("receiver-a")
        second = await self.start()
        self.assertTrue(second.outcome["ok"], second.outcome)
        self.assertIsNone(unrelated.returncode)
        for fd in Path(f"/proc/{first.child.pid}/fd").glob("*"):
            self.fail(f"dead worker retained descriptor {fd}")

    async def test_unsafe_paths_are_refused_without_changes(self):
        outside = Path(self.temp.name) / "outside"
        outside.write_text("keep")
        for suffix, kind in (("sock", "file"), ("json", "symlink"), ("lock", "symlink")):
            path = self.root / f"receiver-a.{suffix}"
            if suffix == "lock":
                path.unlink()  # Only this test's unused, unheld lock.
            if kind == "symlink":
                path.symlink_to(outside)
            else:
                path.write_text("keep")
            result = await self.start()
            self.assertFalse(result.outcome["ok"], (suffix, result.outcome))
            self.assertTrue(path.exists())
            self.assertEqual(outside.read_text(), "keep")
            path.unlink()

    async def test_root_symlink_or_insecure_permissions_are_rejected(self):
        link = Path(self.temp.name) / "link"
        link.symlink_to(self.root)
        with self.assertRaises(ValueError):
            Runtime(link)
        self.root.chmod(0o755)
        with self.assertRaises(ValueError):
            Runtime(self.root)
        self.root.chmod(0o700)

    async def test_socket_without_metadata_is_ambiguous_not_deleted(self):
        sock = socket.socket(socket.AF_UNIX)
        sock.bind(str(self.root / "receiver-a.sock"))
        sock.close()
        result = await self.start()
        self.assertFalse(result.outcome["ok"])
        self.assertTrue((self.root / "receiver-a.sock").exists())

    async def test_bootstrap_rejects_untrusted_structures_and_is_bounded(self):
        from simquaro.worker import decode_bootstrap, encode_bootstrap
        data = encode_bootstrap(self.config, Scenario(), "a" * 32)
        config, scenario, token = decode_bootstrap(data)
        self.assertEqual(config, self.config)
        self.assertEqual(scenario, Scenario())
        self.assertEqual(token, "a" * 32)
        for bad in (b'{"import":"os.system"}', b'null', b'{}' * 40000,
                    data.replace(b'"model":"fictitious_receiver"', b'"model":"os.system"')):
            with self.assertRaises(ValueError):
                decode_bootstrap(bad)

    async def test_control_run_token_must_match_metadata(self):
        result = await self.start()
        data = json.loads(self.metadata().read_text())
        data["run_token"] = "b" * 32
        self.metadata().write_text(json.dumps(data))
        state = await self.runtime.inspect(self.config)
        self.assertFalse(state["ok"])
        self.assertEqual(state["error"]["code"], "RUN_MISMATCH")
        self.assertIsNone(result.child.returncode)

    async def barrier(self, path):
        async with asyncio.timeout(3):
            while not path.exists():
                await asyncio.sleep(.01)

    async def test_interrupted_startup_cleans_new_worker_and_paths(self):
        marker = self.root / "boot-ready"
        with patch("simquaro.runtime._WORKER_MODULE", "tests.simquaro.support.bootstrap"), patch.dict(
                os.environ, {"SIMQUARO_TEST_BARRIER": str(marker)}):
            task = asyncio.create_task(self.start())
            await self.barrier(marker)
            pid = int(marker.read_text())
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertFalse(Path(f"/proc/{pid}").exists())
        self.assertFalse(self.metadata().exists())
        self.assertFalse((self.root / "receiver-a.sock").exists())

    async def test_startup_deadline_is_five_seconds_and_rolls_back(self):
        marker = self.root / "boot-ready"
        with patch("simquaro.runtime._WORKER_MODULE", "tests.simquaro.support.bootstrap"), patch.dict(
                os.environ, {"SIMQUARO_TEST_BARRIER": str(marker)}):
            before = time.monotonic()
            result = await self.start()
            elapsed = time.monotonic() - before
        self.assertFalse(result.outcome["ok"])
        self.assertEqual(result.outcome["error"]["code"], "STARTUP_TIMEOUT")
        self.assertGreaterEqual(elapsed, 4.8)
        self.assertLess(elapsed, 6)
        self.assertIsNotNone(result.child.returncode)
        self.assertFalse(self.metadata().exists())

    async def test_cancelled_inspection_during_start_never_stops_existing_owner(self):
        helper = await self.helper("hanging")
        task = asyncio.create_task(self.start())
        await self.barrier(self.root / "receiver-a.connected")
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertIsNone(helper.returncode)
        self.assertFalse((self.root / "receiver-a.term-seen").exists())
        self.assertTrue(self.metadata().exists())

    async def test_stop_keeps_lifecycle_lock_through_resistant_exit(self):
        helper = await self.helper("resistant")
        stopping = asyncio.create_task(self.runtime.stop("receiver-a"))
        await self.barrier(self.root / "receiver-a.term-seen")
        starting = asyncio.create_task(self.start(runtime=Runtime(self.root)))
        result = await stopping
        replacement = await starting
        self.assertTrue(result["ok"], result)
        self.assertEqual(await helper.wait(), -signal.SIGKILL)
        self.assertTrue(replacement.outcome["ok"], replacement.outcome)
        self.assertIsNone(replacement.child.returncode)

    async def test_pidfd_open_precedes_birth_validation_and_is_retained(self):
        child = await self.helper("graceful")
        from simquaro import _ownership
        real_open, real_birth, real_signal = os.pidfd_open, _ownership.birth, signal.pidfd_send_signal
        opened = []
        def open_pidfd(pid):
            fd = real_open(pid)
            opened.append(fd)
            return fd
        def read_birth(pid):
            self.assertTrue(opened)
            os.fstat(opened[-1])
            return real_birth(pid)
        def send(fd, sig, *args):
            self.assertEqual(fd, opened[-1])
            os.fstat(fd)
            return real_signal(fd, sig, *args)
        with patch("os.pidfd_open", open_pidfd), patch.object(_ownership, "birth", read_birth), patch(
                "signal.pidfd_send_signal", send):
            result = await self.runtime.stop("receiver-a")
        self.assertTrue(result["ok"], result)
        self.assertEqual(await child.wait(), 0)
        with self.assertRaises(OSError):
            os.fstat(opened[-1])

    async def test_unexpected_path_owner_refused(self):
        from simquaro import _ownership
        path = self.root / "receiver-a.lock"
        path.touch(mode=0o600)
        real_fstat = os.fstat
        identity = path.stat().st_ino
        def foreign_owner(fd):
            info = real_fstat(fd)
            if info.st_ino == identity:
                values = list(info)
                values[4] = os.getuid() + 1
                return os.stat_result(values)
            return info
        with patch.object(_ownership.os, "fstat", foreign_owner):
            result = await self.start()
        self.assertFalse(result.outcome["ok"])
        self.assertEqual(path.stat().st_ino, identity)

    async def test_log_evidence_has_host_provenance_run_boot_and_order(self):
        result = await self.start(scenario=Scenario((FaultEffect("clock_untrusted"),)))
        await control_request(self.root / "receiver-a.sock", "fault.activate", {"name": "frequency_read_failure"})
        await self.runtime.inspect(self.config)
        await self.runtime.stop("receiver-a")
        self.log.seek(0)
        lines = [json.loads(line) for line in self.log.read().splitlines()]
        self.assertTrue(any("FREQUENCY_READ_FAILED" in entry["message"] for entry in lines))
        self.assertTrue(all(entry["instance"] == "receiver-a" for entry in lines))
        self.assertTrue(all(entry["run_token"] == result.outcome["status"]["run_token"] for entry in lines))
        self.assertTrue(all(entry["utc_provenance"] == "host_clock" and entry["utc"].endswith("Z") for entry in lines))
        self.assertEqual([entry["sequence"] for entry in lines], list(range(1, len(lines) + 1)))
        self.assertEqual([entry["monotonic_ns"] for entry in lines], sorted(entry["monotonic_ns"] for entry in lines))
        self.assertIsNotNone(lines[-1]["boot_id"])

    async def test_foreground_os_signals_stop_only_newly_created_children(self):
        existing = await self.start(replace(self.config, name="receiver-b"))
        for sig in (signal.SIGINT, signal.SIGTERM):
            supervisor = await self.helper("supervisor")
            supervisor.send_signal(sig)  # This suite's explicit subprocess handle.
            self.assertEqual(await asyncio.wait_for(supervisor.wait(), 5), 0)
            self.assertIsNone(existing.child.returncode)
            self.assertEqual((await self.runtime.inspect(self.config))["process"], "stopped")

    async def test_interruption_while_subprocess_creation_is_in_flight(self):
        real_spawn = subprocess.Popen
        observed = []
        def cancelled_spawn(*args, **kwargs):
            process = real_spawn(*args, **kwargs)
            observed.append(process)
            asyncio.current_task().cancel()
            return process
        with patch("simquaro.runtime.subprocess.Popen", cancelled_spawn):
            task = asyncio.create_task(self.start())
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertIsNotNone(observed[0].returncode)
        self.assertFalse(self.metadata().exists())
        self.assertFalse((self.root / "receiver-a.sock").exists())

    async def test_metadata_publication_failure_does_not_leak_created_child(self):
        from simquaro import _ownership
        def fail_publish(directory, name, value):
            raise PermissionError("test metadata publication failure")
        with patch.object(_ownership.Directory, "publish", fail_publish):
            result = await self.start()
        self.assertFalse(result.outcome["ok"])
        self.assertIsNotNone(result.child)
        self.assertIsNotNone(result.child.returncode)
        self.assertFalse((self.root / "receiver-a.sock").exists())

    async def test_birth_read_failure_after_spawn_still_reaps_owned_child(self):
        observed = []
        real_spawn = subprocess.Popen
        def capture(*args, **kwargs):
            process = real_spawn(*args, **kwargs)
            observed.append(process)
            return process
        with patch("simquaro.runtime.subprocess.Popen", capture), patch(
                "simquaro.runtime.birth", side_effect=PermissionError("test proc access failure")):
            result = await self.start()
        self.assertFalse(result.outcome["ok"])
        self.assertIsNotNone(result.child)
        self.assertIsNotNone(observed[0].returncode)
        self.assertFalse(self.metadata().exists())

    async def test_worker_descendant_does_not_inherit_lifetime_or_control_fds(self):
        marker = self.root / "descendant-ready"
        with patch("simquaro.runtime._WORKER_MODULE", "tests.simquaro.support.bootstrap"), patch.dict(
                os.environ, {"SIMQUARO_TEST_BARRIER": str(marker), "SIMQUARO_TEST_MODE": "descendant"}):
            first = await self.start()
        self.assertTrue(first.outcome["ok"], first.outcome)
        descendant_pid = int(marker.read_text())
        descendant_fd = os.pidfd_open(descendant_pid)
        try:
            targets = [os.readlink(fd) for fd in Path(f"/proc/{descendant_pid}/fd").iterdir()]
            self.assertFalse(any("receiver-a.lock" in path or "receiver-a.lifecycle" in path for path in targets))
            self.assertFalse(any(path.startswith("socket:") for path in targets))
            await self.runtime.stop("receiver-a")
            second = await self.start()
            self.assertTrue(second.outcome["ok"], second.outcome)
            self.assertTrue(Path(f"/proc/{descendant_pid}").exists())
        finally:
            # pidfd opened from our helper's explicitly reported child identity.
            signal.pidfd_send_signal(descendant_fd, signal.SIGTERM)
            loop = asyncio.get_running_loop()
            ended = loop.create_future()
            def ready():
                if not ended.done():
                    ended.set_result(None)
            loop.add_reader(descendant_fd, ready)
            try:
                await asyncio.wait_for(ended, 2)
            finally:
                loop.remove_reader(descendant_fd)
            os.close(descendant_fd)

    async def test_immediate_worker_exit_is_reaped_and_does_not_leave_paths(self):
        marker = self.root / "exited"
        with patch("simquaro.runtime._WORKER_MODULE", "tests.simquaro.support.bootstrap"), patch.dict(
                os.environ, {"SIMQUARO_TEST_BARRIER": str(marker), "SIMQUARO_TEST_MODE": "exit"}):
            result = await self.start()
        self.assertFalse(result.outcome["ok"])
        self.assertIsNotNone(result.child)
        self.assertEqual(await result.child.wait(), 3)
        self.assertFalse(Path(f"/proc/{result.child.pid}").exists())
        self.assertFalse(self.metadata().exists())
        self.assertFalse((self.root / "receiver-a.sock").exists())

    async def test_pidfd_capture_failure_closes_bootstrap_without_pid_signal(self):
        from simquaro import runtime
        real_open = os.pidfd_open
        observed = []
        real_spawn = subprocess.Popen
        def capture(*args, **kwargs):
            process = real_spawn(*args, **kwargs)
            observed.append(process)
            return process
        def fail_child(pid):
            if pid != os.getpid():
                raise PermissionError("test pidfd capture failure")
            return real_open(pid)
        with patch.object(runtime.subprocess, "Popen", capture), patch("os.pidfd_open", fail_child):
            result = await self.start()
        self.assertFalse(result.outcome["ok"])
        self.assertIsNotNone(observed[0].returncode)
        self.assertFalse(self.metadata().exists())
        self.assertFalse((self.root / "receiver-a.sock").exists())
