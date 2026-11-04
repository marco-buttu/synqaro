"""Private subprocess entry. Only bounded JSON data crosses the bootstrap pipe.

This is not a CLI: the launcher passes three explicit descriptors, never Python
expressions, imported model paths, pickle data or an inventory file.
"""

import asyncio
from datetime import datetime, timezone
import json
import logging
import os
import re
import signal
import socket
import sys
import time

from simquaro.config import InstanceConfig, instance_record, instance_from_record
from simquaro.control import ControlServer
from simquaro.faults import FaultEffect, FaultRule, Scenario
from simquaro.registry import get_model
from simquaro.server import HardwareServer
from simquaro._ownership import _unique


BOOTSTRAP_BYTES = 65536


def _object(value, keys):
    if type(value) is not dict or set(value) != set(keys):
        raise ValueError("Invalid bootstrap fields; supply typed InstanceConfig and Scenario objects.")
    return value


def decode_bootstrap(data):
    try:
        if not isinstance(data, bytes) or len(data) > BOOTSTRAP_BYTES:
            raise ValueError("bootstrap exceeds limit")
        def invalid(_):
            raise ValueError("non-finite value")
        value = json.loads(data, object_pairs_hook=_unique, parse_constant=invalid)
        _object(value, {"version", "config", "scenario", "run_token"})
        if type(value["version"]) is not int or value["version"] != 1:
            raise ValueError("invalid version")
        token = value["run_token"]
        if not isinstance(token, str) or re.fullmatch(r"[0-9a-f]{32}", token) is None:
            raise ValueError("invalid run token")
        config = instance_from_record(value["config"])
        scenario = _object(value["scenario"], {"initial_faults", "rules"})
        if type(scenario["initial_faults"]) is not list or type(scenario["rules"]) is not list:
            raise ValueError("scenario must contain lists")
        initial = tuple(FaultEffect(**_object(item, {"name", "parameters"}))
                        for item in scenario["initial_faults"])
        rules = tuple(FaultRule(**_object(item, {"name", "when", "times", "parameters"}))
                      for item in scenario["rules"])
        scenario = Scenario(initial, rules)
        # Admit model-specific causes/events before starting a worker or touching
        # hardware state; bootstrap never selects an arbitrary import path.
        get_model(config.model).fault_factory(scenario)
        return config, scenario, token
    except (TypeError, ValueError, UnicodeError, RecursionError) as error:
        raise ValueError("Invalid private bootstrap; use validated InstanceConfig and Scenario with supported fields and at most 64 KiB of data.") from error


def encode_bootstrap(config, scenario, run_token):
    if not isinstance(config, InstanceConfig) or not isinstance(scenario, Scenario):
        raise ValueError("Provide a validated InstanceConfig and Scenario.")
    value = {"version": 1, "config": instance_record(config), "run_token": run_token,
             "scenario": {"initial_faults": [{"name": effect.name, "parameters": dict(effect.parameters)}
                                              for effect in scenario.initial_faults],
                          "rules": [{"name": rule.name, "when": rule.when, "times": rule.times,
                                     "parameters": dict(rule.parameters)} for rule in scenario.rules]}}
    # Accumulate bounded output even when supplied identity strings are huge.
    data = bytearray()
    for chunk in json.JSONEncoder(allow_nan=False, separators=(",", ":")).iterencode(value):
        encoded = chunk.encode("ascii")
        if len(data) + len(encoded) > BOOTSTRAP_BYTES:
            raise ValueError("Startup configuration exceeds 64 KiB; shorten its identity fields.")
        data.extend(encoded)
    decode_bootstrap(bytes(data))
    return bytes(data)


class _Evidence(logging.Formatter):
    """Host clock provenance is independent of simulated firmware UTC trust."""

    def __init__(self, name, run_token):
        super().__init__()
        self.name, self.run_token = name, run_token
        self.model = None
        self.sequence = 0

    def format(self, record):
        self.sequence += 1
        value = {"instance": self.name, "run_token": self.run_token, "pid": os.getpid(),
                 "utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                 "utc_provenance": "host_clock", "monotonic_ns": time.monotonic_ns(),
                 "sequence": self.sequence, "boot_id": self.model.boot_id if self.model else None,
                 "level": record.levelname, "message": record.getMessage()}
        if record.exc_info:
            value["exception"] = self.formatException(record.exc_info)
        return json.dumps(value, ensure_ascii=True, separators=(",", ":"))


async def serve(config, scenario, run_token, control_socket):
    formatter = _Evidence(config.name, run_token)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)
    logger = logging.getLogger("simquaro")
    logger.handlers[:] = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    model = hardware = control = None
    try:
        definition = get_model(config.model)
        faults = definition.fault_factory(scenario)
        model = definition.factory(config.settings, faults=faults)
        formatter.model = model
        hardware = HardwareServer(model, config.host, config.port)
        control = ControlServer(control_socket, model, faults, run_token=run_token,
                                hardware_server=hardware)
        await hardware.start()
        await control.start()
        logger.info("worker ready hardware_host=%s hardware_port=%s", hardware.host, hardware.port)
        await stop.wait()
        logger.info("worker stopping")
    except Exception:
        logger.exception("Worker startup/runtime failed; correct endpoint/profile configuration and restart %s", config.name)
        return 1
    finally:
        if control:
            await control.close()
        if hardware:
            await hardware.close()
        if model:
            await model.close()
        control_socket.close()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.remove_signal_handler(sig)
    return 0


def main():
    if len(sys.argv) != 4:
        raise SystemExit("Private worker requires launcher-owned descriptors; start with the runtime API.")
    read_fd, lock_fd, socket_fd = map(int, sys.argv[1:])
    for fd in (read_fd, lock_fd, socket_fd):
        os.set_inheritable(fd, False)
    control_socket = socket.socket(fileno=socket_fd)
    try:
        data = bytearray()
        while len(data) <= BOOTSTRAP_BYTES:
            chunk = os.read(read_fd, BOOTSTRAP_BYTES + 1 - len(data))
            if not chunk:
                break
            data.extend(chunk)
        config, scenario, token = decode_bootstrap(bytes(data))
        os.close(read_fd)
        read_fd = None
        return asyncio.run(serve(config, scenario, token, control_socket))
    finally:
        if read_fd is not None:
            os.close(read_fd)
        control_socket.close()
        os.close(lock_fd)


if __name__ == "__main__":
    raise SystemExit(main())
