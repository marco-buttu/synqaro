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
        applied = await client.request("set", {"name": "frequency", "value": NumericToken("5.5"), "unit": "GHz"})
        self.assertEqual(str(applied.fields["value"]), "5.5")
        self.assertEqual(str((await client.request("get", {"name": "frequency"})).fields["value"]), "5.5")
        for name, fields in (
            ("calibrate", {"name": "calibrate"}),
            ("scan", {"name": "scan", "start": NumericToken("5"), "stop": NumericToken("5.2"),
                      "unit": "GHz", "dwell_ms": NumericToken("1")}),
        ):
            self.assertEqual((await client.request("run", fields)).verb, "accepted")
            async with asyncio.timeout(35 if name == "calibrate" else 25):
                while True:
                    status = await client.request("status", {"name": name})
                    if status.fields["state"] not in ("running", "cancelling"):
                        break
                    await asyncio.sleep(.5)
            self.assertEqual(status.fields["state"], "succeeded")
        self.assertEqual(str((await client.request("get", {"name": "frequency"})).fields["value"]), "5.2")
