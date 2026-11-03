"""Real-clock TCP path with the unmodified advertised receiver profile."""

import asyncio
import unittest

from simquaro.models.fictitious_receiver.config import ReceiverConfig
from synqaro_protocol.codec import NumericToken
from simquaro.models.fictitious_receiver.model import FictitiousReceiverSimulator
from simquaro.server import HardwareServer

try:
    from tests.simquaro.support.client import ConformanceClient
except ImportError:
    ConformanceClient = None


class SmokeTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_clock_set_read_ordinary_calibration_and_scan(self):
        self.assertIsNotNone(ConformanceClient, "test-only conforming client is missing")
        model = FictitiousReceiverSimulator(ReceiverConfig())
        server = HardwareServer(model, "127.0.0.1", 0)
        address = await server.start()
        self.addAsyncCleanup(model.close)
        self.addAsyncCleanup(server.close)
        client = ConformanceClient(*address)
        self.addAsyncCleanup(client.close)
        await client.connect()
        from simquaro.checks import run_checks
        from simquaro.models.fictitious_receiver.checks import CHECKS
        selected = tuple(case for case in CHECKS if case.name in (
            "set_frequency_rounding", "calibrate", "scan"))
        report = await run_checks(client, selected, allow_changes=True)
        self.assertEqual(report.exit_code, 0, report.as_dict())
        self.assertEqual(len(report.results), 3)
        self.assertEqual(model.snapshot()["actual"]["frequency"], "5.2")
