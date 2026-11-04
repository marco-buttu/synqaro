"""Readable test reports use endpoints without requiring simulator administration."""

import asyncio
import json
import sys
import unittest

from tests.simquaro.test_checks import CheckServerCase


class TestCliTests(CheckServerCase):
    async def test_unbound_profile_reports_unsupported_not_success(self):
        self.modules()
        script = (
            "from dataclasses import replace; from simquaro.cli import main; "
            "from simquaro.registry import MODELS; from simquaro.config import InstanceConfig; "
            "MODELS['unbound']=replace(MODELS['fictitious_receiver'],client_factory=None,checks=()); "
            "raise SystemExit(main(['--json','test','receiver-a'],inventory={'receiver-a':"
            "InstanceConfig('receiver-a','unbound','127.0.0.1',1)}))")
        process = await asyncio.create_subprocess_exec(sys.executable, "-c", script,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, _ = await asyncio.wait_for(process.communicate(), 5)
        self.assertEqual(process.returncode, 1)
        self.assertEqual(json.loads(stdout)["error"]["code"], "UNSUPPORTED_PROFILE")

    async def test_cli_reports_five_passes_and_five_permission_skips(self):
        self.modules()
        _, client = await self.client()
        host, port = client.host, client.port
        script = ("from simquaro.cli import main; from simquaro.config import InstanceConfig; "
            "raise SystemExit(main(['--json','test','receiver-a'],inventory={'receiver-a':"
            f"InstanceConfig('receiver-a','fictitious_receiver',{host!r},{port})}}))")
        process = await asyncio.create_subprocess_exec(sys.executable, "-c", script,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await asyncio.wait_for(process.communicate(), 5)
        self.assertEqual(process.returncode, 0, stderr.decode())
        records = [json.loads(line) for line in stdout.splitlines()]
        self.assertEqual(records[0]["event"], "test.started")
        self.assertEqual(records[-1]["event"], "test.finished")
        cases = [record["result"] for record in records if record["event"] == "test.case"]
        self.assertEqual(sum(item["state"] == "passed" for item in cases), 5)
        self.assertEqual(sum(item["state"] == "skipped" for item in cases), 5)
