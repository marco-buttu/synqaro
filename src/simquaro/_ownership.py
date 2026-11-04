"""Linux ownership primitives. Call under the per-instance lifecycle lock.

Directory-relative operations retain the validated directory inode. Neither
lock file is ever unlinked. Only explicit, matching run/inode records authorize
removal of a socket and metadata; connection failure never authorizes removal.
"""

import asyncio
from contextlib import asynccontextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import select
import signal
import socket
import stat
import uuid


class OwnershipError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def name_checked(name):
    if (not isinstance(name, str) or re.fullmatch(r"[a-z][a-z0-9_-]{0,47}", name) is None
            or name == "all"):
        raise OwnershipError("INVALID_NAME", "Select a configured flat instance name, excluding 'all'.")
    return name


def inode(info):
    return [info.st_dev, info.st_ino]


def boot_id():
    return Path("/proc/sys/kernel/random/boot_id").read_text().strip()


def birth(pid):
    # comm can contain spaces and ')'; field 22 follows its final closing ')'.
    fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
    return int(fields[19])


def _private(info, kind, mode=None):
    if (info.st_uid != os.getuid() or stat.S_IFMT(info.st_mode) != kind
            or (mode is not None and stat.S_IMODE(info.st_mode) != mode)
            or (kind == stat.S_IFREG and info.st_nlink != 1)):
        raise OwnershipError("UNSAFE_PATH", "Unexpected path type, owner or permissions; select a private runtime directory owned by your user.")


def _local(path):
    local = {"ext2", "ext3", "ext4", "tmpfs", "ramfs", "xfs", "btrfs", "overlay",
             "aufs", "zfs", "f2fs", "reiserfs", "rootfs"}
    mounts = []
    for line in Path("/proc/self/mountinfo").read_text().splitlines():
        left, right = line.split(" - ", 1)
        mount = re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), left.split()[4])
        if path == mount or path.startswith(mount.rstrip("/") + "/"):
            mounts.append((len(mount), right.split()[0]))
    if not mounts or max(mounts)[1] not in local:
        raise OwnershipError("UNSAFE_FILESYSTEM", "Use a supported local filesystem such as /tmp or XDG_RUNTIME_DIR; network and unknown filesystems are not supported.")


def default_root():
    xdg = os.environ.get("XDG_RUNTIME_DIR")
    if xdg:
        try:
            with Directory(Path(xdg), create=False):
                return Path(xdg) / "simquaro"
        except (OSError, ValueError):
            pass
    return Path(f"/tmp/simquaro-{os.getuid()}")


class Directory:
    def __init__(self, path, *, create=True, expected=None):
        self.path = Path(os.path.abspath(path))
        self.fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            parts = self.path.parts[1:]
            for index, part in enumerate(parts):
                if create and index == len(parts) - 1:
                    try:
                        os.mkdir(part, 0o700, dir_fd=self.fd)
                    except FileExistsError:
                        pass
                next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                                  dir_fd=self.fd)
                os.close(self.fd)
                self.fd = next_fd
            info = os.fstat(self.fd)
            _private(info, stat.S_IFDIR, 0o700)
            self.identity = inode(info)
            if expected is not None and expected != self.identity:
                raise OwnershipError("UNSAFE_PATH", "Runtime directory was replaced; use the original private runtime directory or a new one.")
            _local(str(self.path))
        except BaseException:
            os.close(self.fd)
            raise

    def __enter__(self):
        return self

    def __exit__(self, *_):
        os.close(self.fd)

    def info(self, path, kind, *, missing=True):
        try:
            info = os.stat(path, dir_fd=self.fd, follow_symlinks=False)
        except FileNotFoundError:
            if missing:
                return None
            raise
        _private(info, kind, 0o600 if kind == stat.S_IFREG else None)
        return info

    def lock(self, path):
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC,
                     0o600, dir_fd=self.fd)
        try:
            _private(os.fstat(fd), stat.S_IFREG, 0o600)
            if inode(os.fstat(fd)) != inode(self.info(path, stat.S_IFREG, missing=False)):
                raise OwnershipError("UNSAFE_PATH", "Lock path changed; retry using a stable private runtime directory.")
            return fd
        except BaseException:
            os.close(fd)
            raise

    def read(self, name):
        path = name + ".json"
        if self.info(path, stat.S_IFREG) is None:
            return None
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=self.fd)
        try:
            info = os.fstat(fd)
            _private(info, stat.S_IFREG, 0o600)
            data = os.read(fd, 65537)
            if len(data) > 65536:
                raise ValueError("metadata too large")
            value = json.loads(data, object_pairs_hook=_unique)
            required = {"version", "name", "pid", "uid", "host_boot", "birth", "run_token", "socket", "config"}
            if type(value) is not dict or set(value) != required:
                raise ValueError("invalid metadata keys")
            if (type(value["version"]) is not int or value["version"] != 1 or value["name"] != name
                    or any(type(value[k]) is not int or value[k] < 0 for k in ("pid", "uid", "birth"))
                    or value["pid"] <= 0 or value["birth"] <= 0 or value["uid"] != os.getuid()
                    or not isinstance(value["host_boot"], str)
                    or re.fullmatch(r"[0-9a-f-]{36}", value["host_boot"]) is None
                    or not isinstance(value["run_token"], str)
                    or re.fullmatch(r"[0-9a-f]{32}", value["run_token"]) is None
                    or type(value["socket"]) is not list or len(value["socket"]) != 2
                    or any(type(i) is not int or i < 0 for i in value["socket"])
                    or type(value["config"]) is not dict):
                raise ValueError("invalid metadata identity")
            return value, inode(info)
        except (ValueError, UnicodeError, RecursionError) as error:
            raise OwnershipError("INVALID_METADATA", "Ownership record is ambiguous; use a new private runtime directory or restore its trusted record before retrying.") from error
        finally:
            os.close(fd)

    def publish(self, name, value):
        temporary = name + "." + uuid.uuid4().hex + ".tmp"
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC,
                     0o600, dir_fd=self.fd)
        identity = inode(os.fstat(fd))
        try:
            data = json.dumps(value, allow_nan=False, separators=(",", ":")).encode()
            if len(data) > 65536:
                raise OwnershipError("INVALID_METADATA", "Startup configuration is too large; shorten identity fields.")
            while data:
                data = data[os.write(fd, data):]
            os.fsync(fd)
            # A preceding read/cleanup and lifecycle lock establish absence.
            if self.info(name + ".json", stat.S_IFREG) is not None:
                raise OwnershipError("UNSAFE_PATH", "Metadata appeared during startup; use a stable private runtime directory.")
            os.rename(temporary, name + ".json", src_dir_fd=self.fd, dst_dir_fd=self.fd)
            return identity
        finally:
            os.close(fd)
            self.unlink(temporary, identity, stat.S_IFREG)

    def check_socket(self, record):
        info = self.info(record["name"] + ".sock", stat.S_IFSOCK)
        if info is not None and inode(info) != record["socket"]:
            raise OwnershipError("UNSAFE_PATH", "Control socket belongs to a different run; use its original runtime directory or a new private directory.")
        return info

    def unlink(self, path, identity, kind):
        info = self.info(path, kind)
        if info is not None:
            if inode(info) != identity:
                raise OwnershipError("UNSAFE_PATH", "Path was replaced; use a stable private runtime directory before retrying.")
            os.unlink(path, dir_fd=self.fd)

    def cleanup(self, record, meta_inode):
        current = self.read(record["name"])
        if current is None:
            raise OwnershipError("UNSAFE_PATH", "Ownership record disappeared; retry with a trusted runtime directory.")
        if current != (record, meta_inode):
            raise OwnershipError("RUN_MISMATCH", "Ownership record changed; inspect the current instance before retrying.")
        self.check_socket(record)
        self.unlink(record["name"] + ".sock", record["socket"], stat.S_IFSOCK)
        self.unlink(record["name"] + ".json", meta_inode, stat.S_IFREG)


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def try_lock(fd):
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except BlockingIOError:
        return False


@asynccontextmanager
async def coordinated(root, identity, name):
    name_checked(name)
    with Directory(root, expected=identity) as directory:
        fd = directory.lock(name + ".lifecycle")
        try:
            async with asyncio.timeout(5):
                while not try_lock(fd):
                    await asyncio.sleep(.02)
            yield directory
        finally:
            os.close(fd)


class ProcessIdentity:
    """A retained pidfd, opened BEFORE any PID birth/owner validation."""

    def __init__(self, record):
        self.fd = None
        if record["host_boot"] != boot_id():
            return  # The original host boot has ended; never address this PID.
        try:
            self.fd = os.pidfd_open(record["pid"])
        except ProcessLookupError:
            return
        try:
            if self.exited:
                return
            actual_birth = birth(record["pid"])
            actual_uid = os.stat(f"/proc/{record['pid']}").st_uid
            if self.exited:
                return
            if actual_birth != record["birth"] or actual_uid != record["uid"]:
                raise OwnershipError("IDENTITY_MISMATCH", "Process birth or owner differs from the trusted record; use the original runtime record or a new private directory. No process was signaled.")
        except FileNotFoundError:
            if not self.exited:
                self.close()
                raise OwnershipError("IDENTITY_UNVERIFIED", "Process identity cannot be read; restore access to /proc before retrying.") from None
        except BaseException:
            self.close()
            raise

    @property
    def exited(self):
        return self.fd is None or bool(select.select([self.fd], [], [], 0)[0])

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def send(self, sig):
        if not self.exited:
            try:
                signal.pidfd_send_signal(self.fd, sig)
            except ProcessLookupError:
                pass

    async def wait(self, seconds):
        if self.exited:
            return True
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        def ready():
            if not future.done():
                future.set_result(True)
        loop.add_reader(self.fd, ready)
        try:
            async with asyncio.timeout(seconds):
                await future
            return True
        except TimeoutError:
            return False
        finally:
            loop.remove_reader(self.fd)

    async def terminate(self):
        self.send(signal.SIGTERM)
        escalated = not await self.wait(2)
        if escalated:
            self.send(signal.SIGKILL)
            if not await self.wait(2):
                raise OwnershipError("STOP_UNCONFIRMED", "Target did not exit after SIGKILL; inspect host process/kernel health and retry stop.")
        return escalated
