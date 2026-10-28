import asyncio
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
import math
import unittest

from simquaro.clock import SystemClock
from simquaro.config import InstanceConfig, ReceiverConfig, validate_inventory
from simquaro.instances import load_inventory
from tests.simquaro.support.clock import VirtualClock


class ConfigurationTests(unittest.TestCase):
    def test_default_receiver(self):
        inventory = load_inventory()
        self.assertEqual(set(inventory), {"receiver-a"})
        instance = inventory["receiver-a"]
        self.assertEqual(instance.name, "receiver-a")
        self.assertEqual(instance.model, "fictitious_receiver")
        self.assertEqual(instance.host, "127.0.0.1")
        self.assertEqual(load_inventory()["receiver-a"].port, 9001)
        config = instance.receiver
        self.assertEqual(config.hardware_model, "fictitious_receiver")
        self.assertEqual(config.protocol_version, 1)
        self.assertEqual(config.frequency_min, 1)
        self.assertEqual(config.frequency_max, 10)
        self.assertEqual(config.frequency_resolution, 0.000001)
        self.assertEqual(config.frequency_unit, "GHz")
        self.assertEqual(config.initial_frequency, 5)
        self.assertEqual(config.tuning_duration_ms, 100)
        self.assertEqual(config.stop_duration_ms, 100)
        self.assertEqual(config.calibrate_preparation_ms, 1000)
        self.assertEqual(config.calibrate_measurement_ms, 8000)
        self.assertEqual(config.calibrate_finalization_ms, 1000)
        # A different valid starting value is accepted without rounding it.
        self.assertEqual(replace(config, initial_frequency=5.123456).initial_frequency,
                         5.123456)

    def test_invalid_name_model_range_grid_timing(self):
        instance = load_inventory()["receiver-a"]
        for changes in (
            {"name": "../x"}, {"name": "all"}, {"name": "Receiver"},
            {"name": "a" * 49}, {"name": ""}, {"name": "a\n"},
            {"model": "foreign_model"}, {"model": "os.system"},
            {"host": ""}, {"host": "127.0.0.1\n"},
            {"port": -1}, {"port": 65536}, {"port": True}, {"port": 9001.5},
            {"receiver": None},
        ):
            with self.subTest(instance=changes), self.assertRaises(ValueError):
                replace(instance, **changes)

        for changes in (
            {"protocol_version": 2}, {"protocol_version": True},
            {"hardware_model": "foreign_model"}, {"hardware_id": ""},
            {"firmware_version": ""}, {"firmware_build": "bad\nidentity"},
            {"frequency_min": 0}, {"frequency_max": 11},
            {"frequency_resolution": 0}, {"frequency_resolution": 0.000002},
            {"frequency_unit": "MHz"}, {"frequency_rounding": "truncate"},
            {"initial_frequency": 0.999999}, {"initial_frequency": 10.000001},
            {"initial_frequency": 5.0000005}, {"initial_frequency": math.nan},
            {"initial_frequency": math.inf}, {"initial_frequency": True},
            {"initial_frequency": "5"},
            {"max_message_bytes": 8192}, {"max_pending_requests": 5},
            {"incomplete_message_timeout_ms": 1000}, {"max_tuning_ms": 2000},
            {"calibrate_timeout_ms": 10000}, {"scan_timeout_ms": 21000},
            {"procedure_stop_timeout_ms": 0}, {"scan_points": 9},
            {"scan_max_dwell_ms": 1001}, {"utc_clock_supported": False},
            {"tuning_duration_ms": 0}, {"tuning_duration_ms": 1001},
            {"tuning_duration_ms": 100.5}, {"tuning_duration_ms": True},
            {"stop_duration_ms": 5001}, {"stop_duration_ms": -1},
            {"calibrate_preparation_ms": 0},
            {"calibrate_measurement_ms": 29000},
            {"calibrate_finalization_ms": 30000},
            {"calibrate_finalization_ms": 99},
        ):
            with self.subTest(receiver=changes), self.assertRaises(ValueError):
                replace(instance.receiver, **changes)

    def test_inventory_port_range_and_key_name_agreement(self):
        instance = load_inventory()["receiver-a"]
        for port in (1, 65535):
            with self.subTest(port=port):
                self.assertEqual(validate_inventory({instance.name: replace(instance, port=port)})
                                 [instance.name].port, port)
        self.assertEqual(replace(instance, port=0).port, 0)
        with self.assertRaises(ValueError):
            validate_inventory({instance.name: replace(instance, port=0)})
        with self.assertRaises(ValueError):
            validate_inventory({"receiver-b": instance})

    def test_duplicate_endpoint(self):
        first = load_inventory()["receiver-a"]
        second = replace(first, name="receiver-b")
        with self.assertRaises(ValueError):
            validate_inventory({first.name: first, second.name: second})
        second = replace(second, port=9002)
        self.assertEqual(set(validate_inventory({first.name: first, second.name: second})),
                         {"receiver-a", "receiver-b"})

    def test_inventory_is_not_shared_mutable_state(self):
        first = load_inventory()
        previous = first["receiver-a"]
        first["receiver-a"] = replace(previous, port=9002,
                                      receiver=replace(previous.receiver, initial_frequency=6))
        self.assertEqual(previous.port, 9001)
        self.assertEqual(previous.receiver.initial_frequency, 5)
        self.assertEqual(load_inventory()["receiver-a"].port, 9001)
        self.assertEqual(load_inventory()["receiver-a"].receiver.initial_frequency, 5)
        first.clear()
        self.assertEqual(set(load_inventory()), {"receiver-a"})
        with self.assertRaises(FrozenInstanceError):
            previous.port = 9003
        with self.assertRaises(FrozenInstanceError):
            previous.receiver.initial_frequency = 7
        source = {previous.name: previous}
        result = validate_inventory(source)
        source.clear()
        self.assertEqual(result["receiver-a"].port, 9001)


class ClockTests(unittest.IsolatedAsyncioTestCase):
    async def test_virtual_clock_utc_independent(self):
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        clock = VirtualClock(utc=start)
        sleeper = asyncio.create_task(clock.sleep(2))
        await asyncio.sleep(0)
        clock.advance(1)
        await asyncio.sleep(0)
        self.assertFalse(sleeper.done())
        self.assertEqual(clock.monotonic(), 1)
        self.assertEqual(clock.utcnow(), start + timedelta(seconds=1))
        clock.set_utc(start - timedelta(days=1))
        await asyncio.sleep(0)
        self.assertFalse(sleeper.done())
        self.assertEqual(clock.monotonic(), 1)
        clock.advance(1)
        await sleeper
        self.assertEqual(clock.monotonic(), 2)
        self.assertEqual(clock.utcnow(), start - timedelta(days=1) + timedelta(seconds=1))

    async def test_virtual_clock_wakes_only_due_sleepers(self):
        clock = VirtualClock()
        later = asyncio.create_task(clock.sleep(3))
        sooner = asyncio.create_task(clock.sleep(1))
        cancelled = asyncio.create_task(clock.sleep(1))
        await asyncio.sleep(0)
        cancelled.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await cancelled
        clock.advance(1)
        await sooner
        self.assertFalse(later.done())
        clock.advance(2)
        await later
        await clock.sleep(0)

    async def test_virtual_clock_rejects_invalid_time(self):
        clock = VirtualClock()
        for value in (-1, math.nan, math.inf):
            with self.subTest(value=value), self.assertRaises(ValueError):
                clock.advance(value)
            with self.subTest(value=value), self.assertRaises(ValueError):
                await clock.sleep(value)
        with self.assertRaises(ValueError):
            clock.set_utc(datetime(2026, 1, 1))

    async def test_system_clock_provides_aware_utc_and_elapsed_time(self):
        clock = SystemClock()
        before = clock.monotonic()
        await clock.sleep(0)
        self.assertGreaterEqual(clock.monotonic(), before)
        self.assertEqual(clock.utcnow().utcoffset(), timedelta(0))
