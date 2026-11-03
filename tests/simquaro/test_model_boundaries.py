"""A tiny test-only model exercises the real generic composition and TCP path."""

import asyncio
from contextlib import redirect_stdout, redirect_stderr
from dataclasses import dataclass
import io
import json
import unittest
from unittest.mock import patch

from synqaro_protocol.clock import SystemClock
from simquaro.config import InstanceConfig
from simquaro.faults import FaultContext, FaultController, FaultEffect, Scenario
from synqaro_protocol.codec import NumericToken, Response
from simquaro.server import HardwareServer
from simquaro.worker import encode_bootstrap, decode_bootstrap

try:
    from simquaro import registry
    from simquaro.config import instance_record, instance_from_record
    from simquaro.faults import FaultDefinition
    from simquaro.model import ModelReply
except ImportError:
    registry = None


@dataclass(frozen=True)
class MeterSettings:
    initial: int = 7

    def __post_init__(self):
        if type(self.initial) is not int or self.initial < 0:
            raise ValueError("initial must be a nonnegative integer")


def meter_faults(scenario=Scenario()):
    return FaultController(
        scenario, definitions=(FaultDefinition("probe_failure", True, "Probe fails."),),
        events=("response_ready", "sample_verified"),
        delivery_events=("response_ready", "sample_verified"))


class Meter:
    """Not a second product model; just a fixture with no receiver attributes."""

    def __init__(self, config, *, faults=None, clock=None):
        self.value = config.initial
        self.faults = faults if faults is not None else meter_faults()
        self.clock = clock if clock is not None else SystemClock()
        self.boot_id = "meter-boot"
        self.changed = asyncio.Event()

    def utc_timestamp(self):
        return None

    async def handle(self, request, *, session_id):
        effects, events = (), ()
        if request.verb == "set":
            self.value = int(str(request.fields["value"]))
            if request.fields.get("name") == "sample":
                events = ("sample_verified",)
                effects = self.faults.emit(FaultContext(
                    "sample_verified", session_id, request.request_id, "set", "sample"))
            self.changed.set()
        return ModelReply(Response("ok", request.request_id, {
            "value": NumericToken(str(self.value))}), effects, delivery_events=events)

    def snapshot(self):
        return {"reported": {"general": {"health": "ok", "activity": "idle"}}}

    async def reboot(self):
        self.boot_id = "meter-reboot"

    async def close(self):
        pass


class ModelBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.assertIsNotNone(registry, "explicit model registry and neutral interfaces are missing")
        definition = registry.ModelDefinition(MeterSettings, Meter, meter_faults, {}, "settings")
        self.registered = patch.dict(registry.MODELS, {"test_meter": definition})
        self.registered.start()
        self.addCleanup(self.registered.stop)

    async def start_server(self):
        config = InstanceConfig("meter-a", "test_meter", "127.0.0.1", 0,
                                settings=MeterSettings(9))
        definition = registry.get_model(config.model)
        model = definition.factory(config.settings, faults=definition.fault_factory())
        server = HardwareServer(model, config.host, config.port)
        address = await server.start()
        self.addAsyncCleanup(model.close)
        self.addAsyncCleanup(server.close)
        reader, writer = await asyncio.open_connection(*address)
        async def close_peer():
            writer.close()
            await writer.wait_closed()
        self.addAsyncCleanup(close_peer)
        return model, reader, writer

    async def test_registered_model_configuration_and_bootstrap_are_not_receiver_specific(self):
        config = InstanceConfig("meter-a", "test_meter", "127.0.0.1", 9002,
                                settings=MeterSettings(11))
        record = {"name": "meter-a", "model": "test_meter", "host": "127.0.0.1",
                  "port": 9002, "settings": {"initial": 11}}
        self.assertEqual(instance_record(config), record)
        self.assertEqual(instance_from_record(record), config)
        restored, scenario, token = decode_bootstrap(encode_bootstrap(config, Scenario(), "a" * 32))
        self.assertEqual(restored, config)
        self.assertEqual(scenario, Scenario())
        self.assertEqual(token, "a" * 32)

    async def test_receiver_records_keep_the_original_json_shape(self):
        from simquaro.instances import load_inventory
        config = load_inventory()["receiver-a"]
        record = instance_record(config)
        self.assertEqual(set(record), {"name", "model", "host", "port", "receiver"})
        self.assertEqual(record["receiver"]["initial_frequency"], 5)
        self.assertEqual(instance_from_record(record), config)

    async def test_unknown_models_wrong_settings_and_unknown_record_fields_are_rejected(self):
        with self.assertRaises(ValueError):
            InstanceConfig("meter-a", "os.system", "127.0.0.1", 9002)
        with self.assertRaises(ValueError):
            InstanceConfig("meter-a", "test_meter", "127.0.0.1", 9002, settings={"initial": 1})
        with self.assertRaises(ValueError):
            instance_from_record({"name": "meter-a", "model": "test_meter", "host": "127.0.0.1",
                                  "port": 9002, "settings": {"initial": 1, "extra": True}})
        config = InstanceConfig("meter-a", "test_meter", "127.0.0.1", 9002)
        with self.assertRaises(ValueError):
            encode_bootstrap(config, Scenario((FaultEffect("synthesizer_failure"),)), "a" * 32)

    async def test_fault_catalog_is_selected_per_model_and_does_not_leak(self):
        from simquaro.cli import main
        config = InstanceConfig("meter-a", "test_meter", "127.0.0.1", 9002)
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            result = main(["--json", "fault", "list", "meter-a"], inventory={"meter-a": config})
        self.assertEqual(result, 0, errors.getvalue())
        names = {item["name"] for item in json.loads(output.getvalue())["result"]["catalog"]}
        self.assertIn("probe_failure", names)
        self.assertNotIn("synthesizer_failure", names)
        self.assertIn("drop_response", names)
        faults = meter_faults()
        faults.activate("probe_failure")
        with self.assertRaises(ValueError):
            FaultController().activate("probe_failure")
        with self.assertRaises(ValueError):
            faults.schedule("drop_response", when="frequency_set_verified")
        self.assertTrue(faults.is_active("probe_failure"))

    async def test_session_uses_model_clock_quality_without_receiver_fault_names(self):
        _, reader, writer = await self.start_server()
        writer.write(b"#get <id=1>: name=sample\n")
        self.assertEqual(await asyncio.wait_for(reader.readline(), 1), b"#ok <id=1>: value=9\n")
        writer.write(b"#get <id=1>: name=sample\n")
        reply = await asyncio.wait_for(reader.readline(), 1)
        self.assertIn(b"code=ID_NOT_INCREASING", reply)
        self.assertNotIn(b"received_at", reply)

    async def test_only_declared_model_events_release_domain_reorder_holds(self):
        model, reader, writer = await self.start_server()
        model.faults.schedule("reorder_responses", when="sample_verified")
        writer.write(b"#set <id=1>: name=sample, value=10\n")
        await asyncio.wait_for(model.changed.wait(), 1)
        writer.write(b"#set <id=2>: name=other, value=11\n")
        self.assertEqual(await asyncio.wait_for(reader.readline(), 1), b"#ok <id=2>: value=11\n")
        writer.write(b"#set <id=3>: name=sample, value=12\n")
        self.assertEqual(await asyncio.wait_for(reader.readline(), 1), b"#ok <id=3>: value=12\n")
        self.assertEqual(await asyncio.wait_for(reader.readline(), 1), b"#ok <id=1>: value=10\n")
