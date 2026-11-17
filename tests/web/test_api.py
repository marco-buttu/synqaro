"""Required optional-web acceptance: strict local API and real simulator TCP."""

import asyncio
from dataclasses import replace
import importlib
import json
from pathlib import Path
import socket
import tempfile
import unittest

import httpx

from simquaro.configuration import ConfigStore, InventoryEntry, entry_record


ORIGIN = "http://127.0.0.1:8765"
HEADERS = {"Origin": ORIGIN, "X-Simquaro-Client": "1"}


class ApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="sq-api-")
        self.addCleanup(self.temp.cleanup)
        self.store = ConfigStore(Path(self.temp.name) / "instances.json")
        snapshot = self.store.initialize()
        entry = snapshot.entries["receiver-a"]
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            entry = replace(entry, config=replace(entry.config, port=sock.getsockname()[1]))
        physical = InventoryEntry(replace(entry.config, name="physical-b", port=1), "hardware")
        self.snapshot = self.store.save({"receiver-a": entry, "physical-b": physical}, expected_revision=snapshot.revision)
        try: module = importlib.import_module("simquaro.web.app")
        except ImportError: self.fail("Local HTTP API is missing")
        self.app = module.create_app(self.store, runtime_root=Path(self.temp.name) / "run", origin=ORIGIN)
        self.lifespan = self.app.router.lifespan_context(self.app)
        await self.lifespan.__aenter__()
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url=ORIGIN, headers=HEADERS)
        self.addAsyncCleanup(self.client.aclose)

    async def asyncTearDown(self):
        if hasattr(self, "lifespan"): await self.lifespan.__aexit__(None, None, None)

    async def post(self, path, body):
        return await self.client.post(path, json=body)

    async def job(self, action, **extra):
        response = await self.post("/api/targets/receiver-a/lifecycle", {"action": action, **extra})
        self.assertEqual(response.status_code, 202, response.text)
        jid = response.json()["result"]["id"]
        for _ in range(150):
            record = (await self.client.get("/api/jobs/" + jid)).json()["result"]
            if record["state"] != "running": return record
            await asyncio.sleep(.02)
        self.fail("Job failed to finish")

    async def test_inventory_config_and_observation_do_not_connect_hardware(self):
        targets = (await self.client.get("/api/targets")).json()["result"]["targets"]
        self.assertEqual([t["name"] for t in targets], ["receiver-a", "physical-b"])
        self.assertEqual(len(self.app.state.sessions._sessions), 0)
        response = await self.client.get("/api/config")
        self.assertEqual(response.json()["result"]["revision"], self.snapshot.revision)
        self.assertEqual((await self.client.get("/api/targets/receiver-a/admin")).json()["result"]["state"], "stopped")
        self.assertIn("default-src 'self'", response.headers["content-security-policy"])

    async def test_management_distinguishes_external_process_and_preserves_it_on_shutdown(self):
        external = await self.app.state.runtime.start(self.snapshot.entries['receiver-a'].config)
        self.addAsyncCleanup(self.app.state.runtime.stop, 'receiver-a')
        response = await self.client.get('/api/management')
        self.assertEqual(response.status_code, 200)
        rows = {r['name']: r for r in response.json()['result']['targets']}
        self.assertEqual((rows['receiver-a']['state'], rows['receiver-a']['owner']), ('running', 'external'))
        self.assertEqual(rows['physical-b']['state'], 'disconnected')
        self.assertFalse(self.app.state.sessions._sessions)
        await self.job('start')  # Observing an existing process does not adopt it.
        await self.app.state.jobs.close()
        self.assertEqual((await self.app.state.runtime.inspect(self.snapshot.entries['receiver-a'].config))['outcome'], 'running')

    async def test_persistent_connection_is_discoverable_survives_lease_and_closes_at_shutdown(self):
        await self.job('start')
        response = await self.post('/api/sessions', {'target':'receiver-a', 'mode':'managed', 'persistent':True})
        self.assertEqual(response.status_code, 200, response.text)
        sid = response.json()['result']['id']
        self.app.state.sessions._sessions[sid].deadline = 0
        await self.app.state.sessions.expire()
        rows = (await self.client.get('/api/management')).json()['result']['targets']
        row = next(r for r in rows if r['name']=='receiver-a')
        self.assertEqual(row['owner'], 'gui')
        self.assertEqual(row['sessions'][0]['id'], sid)
        self.assertEqual(row['sessions'][0]['state'], 'connected')
        again = await self.post('/api/sessions', {'target':'receiver-a', 'mode':'managed', 'persistent':True})
        self.assertEqual(again.json()['result']['id'], sid)
        conflict = await self.post('/api/sessions', {'target':'receiver-a', 'mode':'raw', 'persistent':True})
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(len(self.app.state.sessions._sessions), 1)
        await self.app.state.sessions.close()
        self.assertFalse(self.app.state.sessions._sessions)
        await self.app.state.jobs.close()
        self.assertEqual((await self.app.state.runtime.inspect(self.snapshot.entries['receiver-a'].config))['outcome'], 'stopped')

    async def test_hardware_connection_failure_is_retained_without_simulator_lifecycle(self):
        response = await self.post('/api/targets/physical-b/connection', {'action':'connect'})
        self.assertEqual(response.status_code, 202, response.text)
        jid = response.json()['result']['id']
        for _ in range(100):
            record = (await self.client.get('/api/jobs/'+jid)).json()['result']
            if record['state'] != 'running': break
            await asyncio.sleep(.02)
        self.assertEqual(record['state'], 'failed')
        rows = (await self.client.get('/api/management')).json()['result']['targets']
        row = next(r for r in rows if r['name']=='physical-b')
        self.assertEqual(row['state'], 'disconnected')
        self.assertEqual(row['job']['id'], jid)
        self.assertFalse(self.app.state.sessions._sessions)

    async def test_repeated_start_preserves_persistent_connection_and_observation_sends_no_requests(self):
        await self.job('start')
        sid = (await self.post('/api/sessions', {'target':'receiver-a','mode':'managed','persistent':True})).json()['result']['id']
        before = (await self.client.get(f'/api/sessions/{sid}/events')).json()['result']['newest']
        await self.job('start')
        for _ in range(3): await self.client.get('/api/management')
        after = await self.client.get(f'/api/sessions/{sid}/events')
        self.assertEqual(after.status_code, 200)
        self.assertEqual(after.json()['result']['newest'], before)

    async def test_real_hardware_connection_reports_remote_loss_and_can_reconnect(self):
        from simquaro.server import HardwareServer
        from simquaro.models.fictitious_receiver.model import FictitiousReceiverSimulator
        model = FictitiousReceiverSimulator(self.snapshot.entries['physical-b'].config.settings)
        server = HardwareServer(model, '127.0.0.1', 0)
        await server.start()
        self.addAsyncCleanup(model.close)
        self.addAsyncCleanup(server.close)
        entries = dict(self.snapshot.entries)
        entries['physical-b'] = replace(entries['physical-b'], config=replace(entries['physical-b'].config, port=server.port))
        self.store.save(entries, expected_revision=self.snapshot.revision)
        response = await self.post('/api/sessions', {'target':'physical-b','mode':'managed','persistent':True})
        self.assertEqual(response.status_code, 200, response.text)
        rows = (await self.client.get('/api/management')).json()['result']['targets']
        self.assertEqual(next(r for r in rows if r['name']=='physical-b')['state'], 'connected')
        await server.close()
        for _ in range(100):
            rows = (await self.client.get('/api/management')).json()['result']['targets']
            if next(r for r in rows if r['name']=='physical-b')['state'] == 'disconnected': break
            await asyncio.sleep(.01)
        self.assertEqual(next(r for r in rows if r['name']=='physical-b')['state'], 'disconnected')
        repeat = await self.post('/api/sessions', {'target':'physical-b','mode':'managed','persistent':True})
        self.assertNotEqual(repeat.status_code, 200, 'A dead connection must not be reported as a successful Connect')

    async def test_foreign_origins_hosts_missing_header_and_oversized_body_reject_before_side_effects(self):
        for headers in ({"Origin": "https://foreign.invalid"}, {"Origin": "null"},
                        {"Host": "foreign.invalid"}, {"Sec-Fetch-Site": "cross-site"},
                        {"X-Simquaro-Client": "0"}):
            response = await self.client.post("/api/sessions", json={"target": "receiver-a", "mode": "raw"}, headers=headers)
            self.assertEqual(response.status_code, 403, response.text)
        large = await self.client.post("/api/sessions", content=b" " * 1048577, headers={"Content-Type": "application/json"})
        self.assertEqual(large.status_code, 413)
        self.assertFalse(self.app.state.sessions._sessions)

    async def test_invalid_json_unknown_fields_targets_and_physical_admin_are_rejected(self):
        for content in (b'{"mode":"raw","mode":"line"}', b'{"port":NaN}', b'[]'):
            response = await self.client.post("/api/sessions", content=content, headers={"Content-Type": "application/json"})
            self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual((await self.post("/api/sessions", {"target":"receiver-a", "mode":"raw", "host":"foreign"})).status_code, 400)
        self.assertEqual((await self.post("/api/sessions", {"target":"missing", "mode":"raw"})).status_code, 404)
        for action in ("start", "stop", "restart", "apply"):
            self.assertEqual((await self.post("/api/targets/physical-b/lifecycle", {"action":action})).status_code, 403)
        self.assertEqual((await self.client.get("/api/targets/physical-b/faults")).status_code, 403)

    async def test_configuration_save_is_cas_and_does_not_apply_or_change_identity(self):
        record = entry_record(self.snapshot.entries["receiver-a"])
        record["receiver"]["initial_frequency"] = {"number":"6"}
        payload = {"revision": self.snapshot.revision, "record":record}
        response = await self.client.put("/api/config/receiver-a", json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual((await self.client.put("/api/config/receiver-a", json=payload)).status_code, 409)
        self.assertEqual((await self.client.get("/api/targets/receiver-a/admin")).json()["result"]["state"], "stopped")
        saved = response.json()["result"]
        record["name"] = "renamed"
        self.assertEqual((await self.client.put("/api/config/receiver-a", json={"revision":saved["revision"], "record":record})).status_code, 403)

    async def test_lifecycle_managed_raw_faults_and_shared_tests(self):
        started = await self.job("start")
        self.assertEqual(started["state"], "succeeded", started)
        sid = (await self.post("/api/sessions", {"target":"receiver-a", "mode":"managed"})).json()["result"]["id"]
        response = await self.post(f"/api/sessions/{sid}/requests", {"verb":"set", "fields":{
            "name":"frequency", "value":{"number":"5.1234565"}, "unit":"GHz"}})
        self.assertEqual(response.json()["result"]["fields"]["value"], {"number":"5.123457"})
        error = await self.post(f"/api/sessions/{sid}/requests", {"verb":"get", "fields":{"name":"missing"}})
        self.assertEqual(error.status_code, 200)
        self.assertEqual(error.json()["result"]["verb"], "error")
        rejected = await self.post("/api/targets/receiver-a/tests", {"allow_changes":False})
        self.assertEqual(rejected.status_code, 409)
        await self.client.delete("/api/sessions/" + sid, headers={"Content-Type":"application/json"})
        raw = (await self.post("/api/sessions", {"target":"receiver-a", "mode":"raw"})).json()["result"]["id"]
        await self.post(f"/api/sessions/{raw}/requests", {"text": r"#nonsense <id=77>\n"})
        await asyncio.sleep(.02)
        events = (await self.client.get(f"/api/sessions/{raw}/events?after=0")).json()["result"]["events"]
        self.assertTrue(any(e["kind"] == "rx" and "UNKNOWN_VERB" in e.get("data", "") for e in events))
        await self.post(f"/api/sessions/{raw}/heartbeat", {})
        await self.client.delete("/api/sessions/" + raw, headers={"Content-Type":"application/json"})
        faults = (await self.client.get("/api/targets/receiver-a/faults")).json()["result"]
        self.assertTrue(faults["catalog"])
        activate = await self.post("/api/targets/receiver-a/faults", {"action":"activate", "arguments":{"name":"calibration_reference_unavailable"}})
        self.assertEqual(activate.status_code, 200, activate.text)
        clear = await self.post("/api/targets/receiver-a/faults", {"action":"clear", "arguments":{"name":"calibration_reference_unavailable"}})
        self.assertEqual(clear.status_code, 200, clear.text)
        tests = await self.post("/api/targets/receiver-a/tests", {"allow_changes":False})
        jid = tests.json()["result"]["id"]
        for _ in range(100):
            report = (await self.client.get("/api/jobs/" + jid)).json()["result"]
            if report["state"] != "running": break
            await asyncio.sleep(.02)
        self.assertEqual(report["state"], "succeeded", report)
        self.assertEqual(report["result"]["counts"], {"passed":5,"failed":0,"skipped":5})
        listed = (await self.client.get("/api/targets/receiver-a/jobs")).json()["result"]["jobs"]
        self.assertEqual(len(listed), 2)

    async def test_local_validation_is_structured_certain_and_transmits_no_request(self):
        await self.job("start")
        sid = (await self.post("/api/sessions", {"target":"receiver-a", "mode":"managed"})).json()["result"]["id"]
        before = (await self.client.get(f"/api/sessions/{sid}/events")).json()["result"]
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app, raise_app_exceptions=False),
                                    base_url=ORIGIN, headers=HEADERS) as client:
            invalid = await client.post(f"/api/sessions/{sid}/requests", json={"verb":"get", "fields":{"name":"é"}})
            self.assertEqual(invalid.status_code, 400, invalid.text)
            self.assertFalse(invalid.json()["error"]["uncertain"])
            for spelling in ("1e999999999", "1e999999999999999999999999999999999999999999"):
                record = entry_record(self.snapshot.entries["receiver-a"])
                record["receiver"]["tuning_duration_ms"] = {"number":spelling}
                response = await client.put("/api/config/receiver-a", json={"revision":self.snapshot.revision,"record":record})
                self.assertEqual(response.status_code, 400, response.text)
                self.assertFalse(response.json()["error"]["uncertain"])
        after = (await self.client.get(f"/api/sessions/{sid}/events")).json()["result"]
        self.assertEqual([e["data"] for e in after["events"] if e["kind"] == "tx"],
                         [e["data"] for e in before["events"] if e["kind"] == "tx"])
        self.assertEqual(self.store.load().revision, self.snapshot.revision)
        hardware_error = await self.post(f"/api/sessions/{sid}/requests", {"verb":"get","fields":{"name":[]}})
        self.assertEqual(hardware_error.status_code, 200, hardware_error.text)
        self.assertEqual(hardware_error.json()["result"]["fields"]["code"], "INVALID_TYPE")
