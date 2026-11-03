"""One shared suite must remain read-only unless explicitly authorized."""

import asyncio
from dataclasses import replace
import importlib
import unittest

from simquaro.models.fictitious_receiver.config import ReceiverConfig
from simquaro.models.fictitious_receiver.model import FictitiousReceiverSimulator
from simquaro.server import HardwareServer
from synqaro_protocol.client import ProtocolClient
from synqaro_protocol.profiles.fictitious_receiver import FICTITIOUS_RECEIVER_CONTRACT


class CheckServerCase(unittest.IsolatedAsyncioTestCase):
    def modules(self):
        try:
            return (importlib.import_module("simquaro.checks"),
                    importlib.import_module("simquaro.models.fictitious_receiver.checks"))
        except ImportError: self.fail("shared hardware checks are missing")

    async def client(self, read_only=True):
        config = replace(ReceiverConfig(), tuning_duration_ms=1, stop_duration_ms=1,
                         calibrate_preparation_ms=1, calibrate_measurement_ms=1,
                         calibrate_finalization_ms=1)
        model = FictitiousReceiverSimulator(config)
        server = HardwareServer(model, "127.0.0.1", 0)
        address = await server.start()
        self.addAsyncCleanup(model.close)
        self.addAsyncCleanup(server.close)
        client = ProtocolClient(*address, contract=FICTITIOUS_RECEIVER_CONTRACT,
            expected_hardware_id=config.hardware_id, read_only=read_only)
        self.addAsyncCleanup(client.close)
        return model, client

class SharedCheckTests(CheckServerCase):
    async def test_rounding_accepts_equivalent_numeric_spelling(self):
        runner, receiver = self.modules()
        model, client = await self.client(read_only=False)
        from synqaro_protocol.codec import NumericToken, Response
        original = model.handle
        async def alternate(request, *, session_id):
            reply = await original(request, session_id=session_id)
            if reply.response.verb == "ok" and "value" in reply.response.fields:
                fields = {**reply.response.fields, "value": NumericToken("5.1234570")}
                return replace(reply, response=Response("ok", reply.response.request_id, fields))
            return reply
        model.handle = alternate
        case = next(case for case in receiver.CHECKS if case.name == "set_frequency_rounding")
        report = await runner.run_checks(client, (case,), allow_changes=True)
        self.assertEqual(report.exit_code, 0, report.as_dict())

    async def test_default_runs_reads_and_skips_all_five_mutations(self):
        runner, receiver = self.modules()
        model, client = await self.client()
        events = []
        report = await runner.run_checks(client, receiver.CHECKS, allow_changes=False, emit=events.append)
        self.assertEqual([r.state for r in report.results], ["passed"] * 5 + ["skipped"] * 5)
        self.assertEqual(report.exit_code, 0)
        self.assertEqual(len(events), 10)
        self.assertEqual(model.snapshot()["actual"]["frequency"], "5")
        self.assertFalse(model.snapshot()["reported"]["general"]["calibrated"])

    async def test_misclassified_mutation_is_stopped_and_later_mutation_skipped(self):
        runner, _ = self.modules()
        model, client = await self.client()
        async def bad(client): await client.request("run", {"name": "calibrate"})
        report = await runner.run_checks(client, (runner.Check("bad", False, bad),
            runner.Check("later", True, bad)), allow_changes=False)
        self.assertEqual(report.results[0].state, "failed")
        self.assertIn("READ_ONLY_CLIENT", report.results[0].reason)
        self.assertEqual(report.results[1].state, "skipped")
        self.assertEqual(report.exit_code, 1)
        self.assertEqual(model.snapshot()["actual"]["frequency"], "5")

    async def test_full_nominal_suite_reuses_real_client_and_finishes_with_reboot(self):
        runner, receiver = self.modules()
        model, client = await self.client(read_only=False)
        before = model.boot_id
        report = await runner.run_checks(client, receiver.CHECKS, allow_changes=True)
        self.assertEqual([(r.name, r.reason) for r in report.results if r.state != "passed"], [])
        self.assertEqual(report.exit_code, 0)
        self.assertEqual(report.results[-1].name, "reboot")
        self.assertNotEqual(model.boot_id, before)

    async def test_empty_suite_is_not_success(self):
        runner, _ = self.modules()
        _, client = await self.client()
        report = await runner.run_checks(client, (), allow_changes=False)
        self.assertEqual(report.exit_code, 1)

    async def test_lost_set_is_uncertain_and_subsequent_mutation_is_not_executed(self):
        runner, receiver = self.modules()
        model, client = await self.client(read_only=False)
        model.faults.schedule("drop_response", when="frequency_set_verified")
        cases = tuple(case for case in receiver.CHECKS if case.name in ("set_frequency_rounding", "calibrate"))
        report = await runner.run_checks(client, cases, allow_changes=True)
        self.assertEqual([r.state for r in report.results], ["failed", "skipped"])
        self.assertIn("uncertain", report.results[0].reason)
        self.assertEqual(report.exit_code, 1)
        self.assertEqual(model.snapshot()["actual"]["frequency"], "5.123457")
        self.assertFalse(model.snapshot()["reported"]["general"]["calibrated"])

    async def test_wrong_identity_cannot_pass_or_modify_hardware(self):
        runner, receiver = self.modules()
        model, client = await self.client(read_only=False)
        client.expected_hardware_id = "different-physical-unit"
        report = await runner.run_checks(client, receiver.CHECKS, allow_changes=True)
        self.assertEqual(report.exit_code, 1)
        self.assertIn("INCOMPATIBLE_DESCRIPTOR", report.results[0].reason)
        self.assertEqual(model.snapshot()["actual"]["frequency"], "5")

    async def test_busy_precondition_is_incomplete_not_a_pass_and_does_not_cancel_scan(self):
        runner, receiver = self.modules()
        model, client = await self.client(read_only=False)
        from synqaro_protocol.codec import NumericToken as N
        await client.connect()
        await client.request("run", {"name": "scan", "start": N("5"), "stop": N("5.2"),
                                     "unit": "GHz", "dwell_ms": N("1000")})
        case = next(case for case in receiver.CHECKS if case.name == "set_frequency_rounding")
        report = await runner.run_checks(client, (case,), allow_changes=True)
        self.assertEqual(report.exit_code, 1)
        self.assertEqual(report.results[0].state, "skipped")
        self.assertEqual(model.snapshot()["reported"]["general"]["activity"], "scanning")
