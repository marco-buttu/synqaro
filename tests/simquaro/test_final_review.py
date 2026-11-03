"""Regression oracles for the combined whole-branch review corrections."""

import asyncio
from contextlib import redirect_stdout, redirect_stderr
from decimal import localcontext, Inexact
import io
import json
import unittest

from simquaro.cli import main
from simquaro.models.fictitious_receiver.config import ReceiverConfig
from simquaro.faults import FaultContext
from simquaro.protocol import NumericToken as N, Request, parse_response
from simquaro.models.fictitious_receiver.model import FictitiousReceiverSimulator
from tests.simquaro.support.client import LocalFailure, _descriptor, _refresh_usable
from tests.simquaro.support.clock import VirtualClock
from tests.simquaro.test_conformance import DESCRIPTOR, ScriptedClientCase, ok, wire_id
from tests.simquaro.test_server import RawSessionCase, turns


class PhysicalInvalidationTests(unittest.IsolatedAsyncioTestCase):
    async def model(self):
        model = FictitiousReceiverSimulator(ReceiverConfig(), clock=VirtualClock())
        self.addAsyncCleanup(model.close)
        return model

    async def tick(self, model, seconds):
        await turns()
        model.clock.advance(seconds)
        await turns()

    async def request(self, model, verb, **fields):
        return (await model.handle(Request(verb, 1, {}, fields), session_id="a")).response

    def activate(self, model, scheduled):
        if scheduled:
            model.faults.schedule("synthesizer_failure", when="response_ready")
            model.faults.emit(FaultContext("response_ready"))
        else:
            model.faults.activate("synthesizer_failure")

    async def test_transient_scan_failure_is_independent_of_polling_and_activation_path(self):
        for scheduled in (False, True):
            for poll in (False, True):
                with self.subTest(scheduled=scheduled, poll=poll):
                    model = await self.model()
                    await self.request(model, "run", name="scan", start=N("5"), stop=N("6"),
                                       unit="GHz", dwell_ms=N("1000"))
                    await self.tick(model, .1)
                    await self.tick(model, .2)
                    self.activate(model, scheduled)
                    if poll:
                        model.snapshot()
                    await self.tick(model, .4)
                    model.faults.clear("synthesizer_failure")
                    await self.tick(model, .4)
                    # Check autonomous outcome before any diagnostic observation.
                    status = model._procedures.status("scan")
                    self.assertEqual(status["state"], "failed")
                    self.assertEqual(status["error_code"], "FREQUENCY_LOCK_FAILED")
                    self.assertEqual(str(status["points_completed"]), "0")
                    snap = model.snapshot()
                    self.assertFalse(snap["actual"]["frequency_verified"])
                    self.assertEqual([e["code"] for e in snap["incidents"]],
                                     ["SYNTHESIZER_FAILURE", "FREQUENCY_LOCK_FAILED"])
                    for _ in range(9):
                        await self.tick(model, .1)
                        await self.tick(model, 1)
                    self.assertEqual(model._procedures.status("scan"), status)

    async def test_transient_fault_invalidates_calibration_and_requires_fresh_verification(self):
        for scheduled in (False, True):
            with self.subTest(scheduled=scheduled):
                model = await self.model()
                await self.request(model, "run", name="calibrate")
                for step in (.1, .9, 8, .1, .9):
                    await self.tick(model, step)
                self.assertTrue(model.snapshot()["reported"]["general"]["calibrated"])
                self.activate(model, scheduled)
                model.faults.clear("synthesizer_failure")
                reading = await self.request(model, "get", name="frequency")
                self.assertEqual(reading.fields.get("reason"), "UNVERIFIED")
                self.assertFalse(model.snapshot()["reported"]["general"]["calibrated"])
                setting = asyncio.create_task(self.request(model, "set", name="frequency", value=N("5"), unit="GHz"))
                await self.tick(model, .1)
                self.assertEqual((await setting).verb, "ok")
                self.assertTrue(model.snapshot()["actual"]["frequency_verified"])
                self.assertFalse(model.snapshot()["reported"]["general"]["calibrated"])
                await self.request(model, "run", name="calibrate")
                for step in (.1, .9, 8, .1, .9):
                    await self.tick(model, step)
                self.assertTrue(model.snapshot()["reported"]["general"]["calibrated"])

    async def test_transient_fault_during_tuning_or_calibration_never_earns_success(self):
        for phase in ("tuning", "measurement"):
            for poll in (False, True):
                with self.subTest(phase=phase, poll=poll):
                    model = await self.model()
                    await self.request(model, "run", name="calibrate")
                    if phase == "measurement":
                        await self.tick(model, .1)
                        await self.tick(model, .9)
                    else:
                        await turns()
                    self.activate(model, False)
                    if poll:
                        model.snapshot()
                    model.faults.clear("synthesizer_failure")
                    for step in (.1, .9, 8, .1, .9):
                        await self.tick(model, step)
                    status = model._procedures.status("calibrate")
                    self.assertEqual(status["state"], "failed")
                    self.assertEqual(status["error_code"], "FREQUENCY_LOCK_FAILED")

    async def test_incident_log_explains_known_code_and_retains_context(self):
        model = await self.model()
        model.faults.activate("synthesizer_failure")
        with self.assertLogs("simquaro.models.fictitious_receiver.model", level="INFO") as logs:
            snap = model.snapshot()
        text = " ".join(logs.output)
        self.assertIn("Diagnostics confirm a synthesizer fault", text)
        self.assertIn("Resolve the synthesizer fault", text)
        self.assertIn(model.boot_id, text)
        self.assertIn("monotonic", text)
        self.assertEqual(snap["incidents"][0]["code"], "SYNTHESIZER_FAILURE")


class MetadataTests(RawSessionCase):
    async def test_client_attribution_preserves_numeric_connection_ids_and_validation(self):
        reader, writer = await self.connect()
        other, other_writer = await self.connect()
        frames = [
            (b'#status <id=01, client_id=alice>\n', b'#ok <id=1>'),
            (b'#get <id=2, client_id="alice, bob">: name=frequency\n', b'#ok <id=2>'),
            (b'#status <id=3, client_id=[true, 12]>\n', b'#ok <id=3>'),
            (b'#status <id=03, client_id=bob>\n', b'ID_NOT_INCREASING'),
            (b'#status <id=4, mystery=alice>\n', b'UNKNOWN_PARAMETER'),
            (b'#status <id=4>\n', b'ID_NOT_INCREASING'),
            (b'#status <id=5, client_id=alice, client_id=bob>\n', b'DUPLICATE_PARAMETER'),
            (b'#status <id=5>\n', b'ID_NOT_INCREASING'),
        ]
        for frame, expected in frames:
            with self.subTest(frame=frame):
                writer.write(frame)
                self.assertIn(expected, await self.line(reader))
        other_writer.write(b'#status <id=1, client_id=alice>\n')
        self.assertIn(b'#ok <id=1>', await self.line(other))
        writer.write(b'#run <id=6, client_id=alice>: name=calibrate\n')
        self.assertIn(b'#accepted <id=6>', await self.line(reader))
        other_writer.write(b'#cancel <id=2, client_id=bob>: name=calibrate\n')
        self.assertIn(b'#accepted <id=2>', await self.line(other))
        await self.tick(.1)


class NumericValidationTests(unittest.TestCase):
    def test_integer_descriptor_accepts_leading_zeros_but_not_fraction_or_exponent(self):
        for spelling in (b"01", b"0001", b"1.0", b"1e0", b"+1", b"2", b"1" * 65):
            with self.subTest(spelling=spelling):
                response = parse_response(ok(1, DESCRIPTOR.replace(b"protocol_version=1,", b"protocol_version=" + spelling + b",")))
                if spelling in (b"01", b"0001"):
                    _descriptor(response, "example-receiver-01")
                    self.assertEqual(str(response.fields["protocol_version"]), spelling.decode())
                else:
                    with self.assertRaises(LocalFailure):
                        _descriptor(response, "example-receiver-01")

    def test_frequency_grid_is_exact_and_decimal_context_independent(self):
        for spelling, usable in (("6.0000000", True), ("60e-1", True), ("6.0000010", True),
                                  ("6.0000001", False), ("6e999999999", False), ("6e-999999999", False),
                                  ("6." + "0" * 63, False)):
            with self.subTest(spelling=spelling), localcontext() as context:
                context.prec = 2
                context.traps[Inexact] = True
                response = parse_response(ok(4, f"name=frequency, value={spelling}, unit=GHz".encode()))
                if usable:
                    _refresh_usable(("get", "frequency"), response)
                    self.assertEqual(str(response.fields["value"]), spelling)
                else:
                    with self.assertRaises(LocalFailure):
                        _refresh_usable(("get", "frequency"), response)


class NumericRecoveryTests(ScriptedClientCase):
    async def test_lost_set_recovers_from_equivalent_numeric_spellings_without_replay(self):
        self.descriptor = DESCRIPTOR.replace(b"protocol_version=1,", b"protocol_version=01,")
        client = await self.client()
        async def behavior(connection, frame, writer):
            if frame.startswith(b"#set"):
                return
            fields = b'name=frequency, value=6.0000000, unit=GHz' if frame.startswith(b"#get") else None
            writer.write(ok(wire_id(frame), fields) if fields else ok(wire_id(frame)))
        self.behavior = behavior
        setting = asyncio.create_task(client.request("set", {"name": "frequency", "value": N("6"), "unit": "GHz"}))
        await self.tick(2)
        with self.assertRaises(LocalFailure) as failure:
            await setting
        self.assertTrue(failure.exception.uncertain)
        await turns(100)
        self.assertTrue(client.writes_enabled)
        self.assertEqual(str(client.refreshed[("get", "frequency")].fields["value"]), "6.0000000")
        self.assertEqual(sum(frame.startswith(b"#set") for _, frame in self.frames), 1)
        self.assertEqual(len(client.uncertainties), 1)


class RecoveryActionTests(unittest.TestCase):
    def test_unknown_instance_suggestions_are_executable(self):
        output = io.StringIO()
        with redirect_stdout(output), redirect_stderr(io.StringIO()):
            code = main(["--json", "fault", "status", "missing"])
        self.assertEqual(code, 2)
        record = json.loads(output.getvalue())
        for action in record["error"]["actions"]:
            with self.subTest(action=action), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(main(action[1:]), 0)
