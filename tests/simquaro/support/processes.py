"""Owned subprocess sentinels with explicit readiness and signal barriers."""

import asyncio
import fcntl
import os
from pathlib import Path
import signal
import socket
import sys

from simquaro._ownership import Directory, birth, boot_id, inode
from simquaro.config import InstanceConfig, instance_record


def main():
    mode, root, name = sys.argv[1:]
    root = Path(root)
    if mode in ("preserve-normal", "preserve-cancel"):
        from simquaro.runtime import Runtime
        async def preserve_handlers():
            runtime = Runtime(root)
            owned = await runtime.start(InstanceConfig(name, "fictitious_receiver", "127.0.0.1", 0))
            loop = asyncio.get_running_loop()
            seen = set()
            complete = asyncio.Event()
            def received(sig):
                seen.add(sig)
                print(sig.name, flush=True)
                if len(seen) == 2:
                    complete.set()
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, received, sig)
            task = asyncio.create_task(runtime.supervise([owned]))
            await asyncio.sleep(0)
            if mode == "preserve-cancel":
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            else:
                stopped = await runtime.stop(name)
                assert stopped["ok"]
                assert await task == 0
            assert owned.child.returncode is not None
            print("ready", flush=True)
            await complete.wait()
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.remove_signal_handler(sig)
        asyncio.run(preserve_handlers())
        return
    if mode == "supervisor":
        from simquaro.runtime import Runtime
        async def supervise():
            runtime = Runtime(root)
            existing = await runtime.start(InstanceConfig("receiver-b", "fictitious_receiver", "127.0.0.1", 0))
            owned = await runtime.start(InstanceConfig(name, "fictitious_receiver", "127.0.0.1", 0))
            task = asyncio.create_task(runtime.supervise([existing, owned]))
            loop = asyncio.get_running_loop()
            def interrupt(sig):
                (root / (name + ".caller-signal")).write_text(sig.name)
                task.cancel()
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, interrupt, sig)
            try:
                await asyncio.sleep(0)
                print("ready", flush=True)
                return await task
            except asyncio.CancelledError:
                return 0
            finally:
                for sig in (signal.SIGINT, signal.SIGTERM):
                    loop.remove_signal_handler(sig)
        raise SystemExit(asyncio.run(supervise()))
    if mode == "sentinel":
        print("ready", flush=True)
        while True:
            signal.pause()
    with Directory(root) as directory:
        lock = directory.lock(name + ".lock")
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        sock = socket.socket(socket.AF_UNIX)
        sock.bind(str(root / (name + ".sock")))
        # Deliberately no listener: control is unavailable, process still alive.
        record = {"version": 1, "name": name, "pid": os.getpid(), "uid": os.getuid(),
                  "host_boot": boot_id(), "birth": birth(os.getpid()), "run_token": "c" * 32,
                  "socket": inode((root / (name + ".sock")).stat()),
                  "config": instance_record(InstanceConfig(name, "fictitious_receiver", "127.0.0.1", 0))}
        directory.publish(name, record)
        def terminate(*_):
            (root / (name + ".term-seen")).touch()
            if mode == "graceful":
                raise SystemExit(0)
        signal.signal(signal.SIGTERM, terminate)
        if mode == "hanging":
            sock.listen()
        print("ready", flush=True)
        try:
            if mode == "hanging":
                connection, _ = sock.accept()
                (root / (name + ".connected")).touch()
            while True:
                signal.pause()
        finally:
            sock.close()
            os.close(lock)


if __name__ == "__main__":
    main()
