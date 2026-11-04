"""Production client safety and wire evidence, independent of simulator internals."""

import importlib
import unittest

from tests.simquaro.test_conformance import ScriptedClientCase, ok


class ProductionClientTests(ScriptedClientCase):
    def production(self, **options):
        try:
            module = importlib.import_module("synqaro_protocol.client")
            profile = importlib.import_module("synqaro_protocol.profiles.fictitious_receiver")
        except ImportError:
            self.fail("production client and explicit receiver profile are missing")
        return module.ProtocolClient(*self.address, clock=self.clock,
            contract=profile.FICTITIOUS_RECEIVER_CONTRACT,
            expected_hardware_id="example-receiver-01", **options)

    async def test_read_only_gate_rejects_mutations_before_transmission(self):
        client = self.production(read_only=True)
        self.clients.append(client)
        await client.connect()
        before = list(self.frames)
        from synqaro_protocol.client import LocalFailure
        self.assertTrue(client.ready)
        self.assertFalse(client.writes_enabled)
        for verb in ("set", "run", "cancel", "reboot"):
            with self.subTest(verb=verb), self.assertRaises(LocalFailure) as caught:
                await client.request(verb, {"name": "calibrate"})
            self.assertEqual(caught.exception.code, "READ_ONLY_CLIENT")
        self.assertEqual(self.frames, before)
        await client.request("status")

    async def test_observer_sees_exact_wire_without_breaking_client(self):
        events = []
        def observe(event):
            events.append(event)
            raise RuntimeError("unrelated consumer error")
        client = self.production(observe=observe)
        self.clients.append(client)
        await client.connect()
        response = await client.request("status")
        self.assertEqual(response.verb, "ok")
        tx = [event.wire for event in events if event.kind == "tx"]
        rx = [event.wire for event in events if event.kind == "rx"]
        self.assertEqual(tx, [b'#get <id=1>: name="configuration"\n',
                             b'#status <id=2>\n', b'#status <id=3>\n'])
        self.assertIn(ok(3), rx)
        self.assertLessEqual(len(client.evidence), 256)

    async def test_list_valued_name_returns_the_actual_hardware_error(self):
        client = self.production()
        self.clients.append(client)
        await client.connect()
        async def behavior(connection, frame, writer):
            writer.write(b'#error <id=3>: code=INVALID_TYPE, parameter=name, expected=string\n')
        self.behavior = behavior
        response = await client.request("get", {"name": []})
        self.assertEqual(response.verb, "error")
        self.assertEqual(response.fields["code"], "INVALID_TYPE")
        self.assertEqual(self.frames[-1][1], b'#get <id=3>: name=[]\n')
