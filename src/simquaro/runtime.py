"""Foreground Linux process lifecycle: one independent subprocess per instance.

All operations return per-instance evidence. Runtime query success is separate
from simulated health, and no status/readiness operation queries hardware TCP.
Only supervise() installs process signal handlers, and only for its duration.
"""

import asyncio
from collections.abc import Sequence
from dataclasses import asdict, dataclass
import os
from pathlib import Path
import secrets
import signal
import socket
import stat
import subprocess
import sys

from simquaro._ownership import (Directory, OwnershipError, ProcessIdentity, birth,
                                boot_id, coordinated, default_root, inode, name_checked, try_lock)
from simquaro.config import InstanceConfig
from simquaro.control import control_request
from simquaro.faults import Scenario
from simquaro.worker import encode_bootstrap


_WORKER_MODULE = "simquaro.worker"


class _Child:
    """Retain one unreaped Popen and one pidfd until the single async reaper.

    Capture is synchronous: no watcher, poll, wait or await may reap the child
    between Popen and pidfd_open. Thus its PID cannot have been reused. Every
    waiter shares one task and only that task registers/removes the fd reader.
    """

    def __init__(self, process, pidfd, name, run_token):
        self._process, self._pidfd = process, pidfd
        self.name, self.run_token = name, run_token
        self._completion = asyncio.create_task(self._reap())

    @property
    def pid(self):
        return self._process.pid

    @property
    def returncode(self):
        return self._process.returncode

    def signal(self, sig):
        if self._pidfd is not None:
            try:
                signal.pidfd_send_signal(self._pidfd, sig)
            except ProcessLookupError:
                pass

    async def _reap(self):
        loop = asyncio.get_running_loop()
        done = loop.create_future()
        def ready():
            if not done.done():
                done.set_result(None)
        loop.add_reader(self._pidfd, ready)
        try:
            await done
            # pidfd readability proves exit: this wait cannot block the loop.
            return self._process.wait(timeout=0)
        finally:
            loop.remove_reader(self._pidfd)
            os.close(self._pidfd)
            self._pidfd = None

    async def wait(self):
        return await asyncio.shield(self._completion)

    async def terminate(self):
        self.signal(signal.SIGTERM)
        try:
            async with asyncio.timeout(2):
                await self.wait()
            return False
        except TimeoutError:
            self.signal(signal.SIGKILL)
            try:
                async with asyncio.timeout(2):
                    await self.wait()
            except TimeoutError:
                raise OwnershipError("STOP_UNCONFIRMED", "Owned child did not exit after SIGKILL; inspect host process/kernel health and retry stop.") from None
            return True


@dataclass(frozen=True)
class StartResult:
    outcome: dict
    child: _Child | None = None


def _outcome(name, outcome, **values):
    return {"version": 1, "ok": True, "instance": name, "outcome": outcome, **values}


def _failure(name, error, **values):
    code = error.code if isinstance(error, OwnershipError) else "RUNTIME_FAILURE"
    if isinstance(error, TimeoutError):
        code, message = "STARTUP_TIMEOUT", "Local startup/coordination exceeded 5 seconds; inspect the instance and retry restart."
    else:
        message = str(error) or "Runtime operation failed; inspect host permissions and configuration before retrying."
        if isinstance(error, OSError):
            message += "; restore runtime directory and /proc access, or choose an accessible private local directory before retrying."
    return {"version": 1, "ok": False, "instance": name, "outcome": "failed", **values,
            "error": {"code": code, "message": message,
                      "actions": [["simquaro", "status", name], ["simquaro", "restart", name]]}}


async def _write_pipe(fd, data):
    os.set_blocking(fd, False)
    loop = asyncio.get_running_loop()
    while data:
        try:
            data = data[os.write(fd, data):]
        except BlockingIOError:
            future = loop.create_future()
            def ready():
                if not future.done():
                    future.set_result(None)
            loop.add_writer(fd, ready)
            try:
                await future
            finally:
                loop.remove_writer(fd)


class Runtime:
    def __init__(self, root: Path | None = None):
        try:
            with Directory(default_root() if root is None else root) as directory:
                self.root, self._directory_identity = directory.path, directory.identity
            # Fail before spawning if the required Linux primitive is unavailable.
            fd = os.pidfd_open(os.getpid())
            os.close(fd)
        except (OSError, AttributeError) as error:
            raise ValueError("Runtime needs a private local directory and Linux pidfd support; use a supported Linux host and a directory owned by your user.") from error
        self._children = {}

    def _coordination(self, name):
        return coordinated(self.root, self._directory_identity, name)

    def _state(self, directory, name, lock_fd):
        free = try_lock(lock_fd)
        metadata = directory.read(name)
        sock = directory.info(name + ".sock", stat.S_IFSOCK)
        if metadata is None:
            if not free or sock is not None:
                raise OwnershipError("AMBIGUOUS_STATE", "A held lock or socket has no trusted ownership record; use the original private runtime directory or a new one.")
            return free, None, None
        record, meta_inode = metadata
        directory.check_socket(record)
        target = ProcessIdentity(record)
        if not target.exited and free:
            target.close()
            raise OwnershipError("AMBIGUOUS_STATE", "A live recorded process does not hold its lifetime lock; inspect its original runtime directory before retrying.")
        if target.exited and not free:
            target.close()
            raise OwnershipError("AMBIGUOUS_STATE", "Another process holds a dead instance's lock; use its original runtime directory or retry after that owner exits.")
        return free, (record, meta_inode), target

    async def _query(self, config, record):
        envelope = await control_request(self.root / (config.name + ".sock"), "status", {})
        common = {"process": "running", "configured": asdict(config), "startup_config": record["config"]}
        if not envelope["ok"]:
            return _failure(config.name, OwnershipError("CONTROL_UNRESPONSIVE", "Process exists but control is unresponsive; run simquaro restart " + config.name + "."),
                            control="unresponsive", control_error=envelope["error"], **common)
        status = envelope["result"]
        if status.get("run_token") != record["run_token"]:
            return _failure(config.name, OwnershipError("RUN_MISMATCH", "Control returned a different process run; inspect the runtime directory before retrying."),
                            control="unverified", **common)
        return _outcome(config.name, "running", control="responsive", status=status, **common)

    async def inspect(self, config: InstanceConfig) -> dict:
        name = config.name
        try:
            async with self._coordination(name) as directory:
                lock_fd = directory.lock(name + ".lock")
                target = None
                try:
                    _, metadata, target = self._state(directory, name, lock_fd)
                    if target is None or target.exited:
                        return _outcome(name, "stopped", process="stopped", control="not_running",
                                        configured=asdict(config), startup_config=metadata[0]["config"] if metadata else None)
                    return await self._query(config, metadata[0])
                finally:
                    if target:
                        target.close()
                    os.close(lock_fd)
        except (OSError, ValueError, TimeoutError) as error:
            return _failure(name, error)

    async def start(self, config, *, scenario=Scenario()) -> StartResult:
        name = config.name
        deadline = asyncio.get_running_loop().time() + 5
        try:
            # Reconstruct immutable validation before touching an existing run.
            token = secrets.token_hex(16)
            bootstrap = encode_bootstrap(config, scenario, token)
            async with self._coordination(name) as directory:
                return await self._start_locked(directory, config, token, bootstrap, deadline)
        except (OSError, ValueError, TimeoutError) as error:
            return StartResult(_failure(name, error))

    async def _start_locked(self, directory, config, token, bootstrap, deadline):
        name = config.name
        lock_fd = directory.lock(name + ".lock")
        target = None
        child = None
        metadata = None
        sock = None
        socket_inode = None
        read_fd = write_fd = None
        process = None
        try:
            async with asyncio.timeout_at(deadline):
                _, previous, target = self._state(directory, name, lock_fd)
                if target is not None and not target.exited:
                    result = await self._query(config, previous[0])
                    if result["ok"]:
                        result["outcome"] = "already_running"
                    return StartResult(result)
                if target is not None:
                    target.close()
                    target = None
                    directory.cleanup(*previous)
                sock = socket.socket(socket.AF_UNIX)
                # Bind relative to the directory inode already validated/opened.
                sock.bind(f"/proc/self/fd/{directory.fd}/{name}.sock")
                socket_inode = inode(directory.info(name + ".sock", stat.S_IFSOCK, missing=False))
                read_fd, write_fd = os.pipe2(os.O_CLOEXEC)
                process = subprocess.Popen(
                    [sys.executable, "-m", _WORKER_MODULE, str(read_fd), str(lock_fd), str(sock.fileno())],
                    pass_fds=(read_fd, lock_fd, sock.fileno()), stdin=asyncio.subprocess.DEVNULL,
                    # Both streams inherit the foreground parent's sink. No pipe
                    # whose output could fill up while nobody is reading it.
                    stdout=None, stderr=None, start_new_session=True)
                # No await or reaper between creation and capture. Popen is held
                # strongly and cannot reap this child implicitly before capture.
                child = _Child(process, os.pidfd_open(process.pid), name, token)
                self._children[token] = child
                child._completion.add_done_callback(lambda _: self._children.pop(token, None))
                record = {"version": 1, "name": name, "pid": process.pid, "uid": os.getuid(),
                          "host_boot": boot_id(), "birth": birth(process.pid), "run_token": token,
                          "socket": socket_inode, "config": asdict(config)}
                target = ProcessIdentity(record)
                meta_inode = directory.publish(name, record)
                metadata = (record, meta_inode)
                os.close(read_fd)
                read_fd = None
                # Parent drops its copy; only the worker keeps the lifetime lock.
                os.close(lock_fd)
                lock_fd = None
                sock.close()
                await _write_pipe(write_fd, bootstrap)
                os.close(write_fd)
                write_fd = None
                while not target.exited:
                    envelope = await control_request(self.root / (name + ".sock"), "status", {},
                                                     timeout=min(2., max(.001, deadline - asyncio.get_running_loop().time())))
                    if envelope["ok"]:
                        status = envelope["result"]
                        if status.get("run_token") != record["run_token"]:
                            raise OwnershipError("RUN_MISMATCH", "Startup control returned a different run; inspect the original runtime directory before retrying.")
                        runtime = status.get("runtime", {})
                        if runtime.get("control") == "ready" and runtime.get("hardware_listener") == "listening":
                            return StartResult(_outcome(name, "started", process="running", control="responsive",
                                                       configured=asdict(config), startup_config=record["config"], status=status), child)
                    await asyncio.sleep(.02)
                raise OwnershipError("WORKER_EXITED", "Worker exited during startup; correct the endpoint/profile error shown in stderr and restart " + name + ".")
        except BaseException as error:
            if socket_inode is None:
                # Querying an existing instance never transfers child ownership,
                # including when that query is cancelled or times out.
                if isinstance(error, (OSError, ValueError, TimeoutError)):
                    return StartResult(_failure(name, error))
                raise
            # Remain under lifecycle coordination through cancellation cleanup.
            async def rollback():
                nonlocal lock_fd, write_fd
                if child is not None:
                    await child.terminate()
                elif process is not None:
                    # pidfd acquisition itself failed: never fall back to a PID
                    # signal. EOF on the private bootstrap lets our worker exit.
                    if write_fd is not None:
                        os.close(write_fd)
                        write_fd = None
                    async with asyncio.timeout(2):
                        while process.poll() is None:
                            await asyncio.sleep(.02)
                if lock_fd is None:
                    lock_fd = directory.lock(name + ".lock")
                if not try_lock(lock_fd):
                    raise OwnershipError("STOP_UNCONFIRMED", "Worker lifetime lock remains held; inspect host process health and retry stop.")
                if metadata is not None:
                    directory.cleanup(*metadata)
                elif socket_inode is not None:
                    directory.unlink(name + ".sock", socket_inode, stat.S_IFSOCK)
            cleanup = asyncio.create_task(rollback())
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                await cleanup
                raise
            except (OSError, ValueError) as cleanup_error:
                if isinstance(error, asyncio.CancelledError):
                    raise cleanup_error from error
                return StartResult(_failure(name, cleanup_error), child)
            if isinstance(error, asyncio.CancelledError):
                raise
            if isinstance(error, (OSError, ValueError, TimeoutError)):
                return StartResult(_failure(name, error), child)
            raise
        finally:
            if target:
                target.close()
            for fd in (lock_fd, read_fd, write_fd):
                if fd is not None:
                    os.close(fd)
            if sock:
                sock.close()

    async def stop(self, name: str) -> dict:
        return await self._stop(name)

    async def _stop(self, name, *, expected=None):
        try:
            name_checked(name)
            async with self._coordination(name) as directory:
                lock_fd = directory.lock(name + ".lock")
                target = None
                try:
                    _, metadata, target = self._state(directory, name, lock_fd)
                    if metadata is None:
                        return _outcome(name, "already_stopped", process="stopped", escalated=False)
                    record, meta_inode = metadata
                    if expected is not None and record["run_token"] != expected:
                        return _outcome(name, "no_longer_owned", process="unverified", escalated=False)
                    running = not target.exited
                    # Cancellation must not release coordination halfway through
                    # escalation or permit a replacement during confirmation.
                    async def finish():
                        escalated = await target.terminate() if running else False
                        if not try_lock(lock_fd):
                            raise OwnershipError("STOP_UNCONFIRMED", "Process exited but its lifetime lock remains held; inspect inherited process ownership and retry stop.")
                        directory.cleanup(record, meta_inode)
                        child = self._children.get(record["run_token"])
                        if child is not None:
                            await child.wait()
                        return _outcome(name, "stopped" if running else "already_stopped",
                                        process="stopped", escalated=escalated)
                    task = asyncio.create_task(finish())
                    try:
                        return await asyncio.shield(task)
                    except asyncio.CancelledError:
                        await task
                        raise
                finally:
                    if target:
                        target.close()
                    os.close(lock_fd)
        except (OSError, ValueError, TimeoutError) as error:
            return _failure(name, error)

    async def restart(self, config, *, scenario=Scenario()) -> StartResult:
        result = await self.stop(config.name)
        if not result["ok"]:
            return StartResult(result)
        return await self.start(config, scenario=scenario)

    async def supervise(self, started: Sequence[StartResult]) -> int:
        children = [result.child for result in started if result.child is not None]
        failure = any(not result.outcome["ok"] for result in started)
        if not children:
            return int(failure)
        loop = asyncio.get_running_loop()
        interrupted = asyncio.Event()
        previous = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
        for sig in previous:
            loop.add_signal_handler(sig, interrupted.set)
        waits = {asyncio.create_task(child.wait()): child for child in children}
        stop_wait = asyncio.create_task(interrupted.wait())
        async def cleanup_owned():
            results = await asyncio.gather(*(self._stop(child.name, expected=child.run_token)
                                             for child in children))
            return any(not result["ok"] for result in results)
        try:
            while waits:
                done, _ = await asyncio.wait([*waits, stop_wait], return_when=asyncio.FIRST_COMPLETED)
                if stop_wait in done:
                    failure |= await cleanup_owned()
                    return int(failure)
                for task in done:
                    child = waits.pop(task)
                    failure |= task.result() != 0
                    result = await self._stop(child.name, expected=child.run_token)
                    failure |= not result["ok"]
            return int(failure)
        except asyncio.CancelledError:
            cleanup = asyncio.create_task(cleanup_owned())
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                await cleanup
            raise
        finally:
            stop_wait.cancel()
            for task in waits:
                task.cancel()
            await asyncio.gather(stop_wait, *waits, return_exceptions=True)
            for sig, handler in previous.items():
                loop.remove_signal_handler(sig)
                signal.signal(sig, handler)
