"""Launch the installed-style foreground CLI and read its actual HTTP listener."""

import json
from pathlib import Path
import select
import signal
import socket
import subprocess
import sys
import tempfile
import unittest
import urllib.request

from simquaro.configuration import ConfigStore


class LaunchTests(unittest.TestCase):
    def test_foreground_json_ready_is_http_ready_and_busy_port_has_action(self):
        with tempfile.TemporaryDirectory(prefix="sq-launch-") as directory:
            store = ConfigStore(Path(directory) / "instances.json")
            store.initialize()
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                port = probe.getsockname()[1]
            args = [sys.executable, "-m", "simquaro", "--json", "--config", str(store.path), "gui", "--port", str(port), "--no-browser"]
            process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                ready, _, _ = select.select([process.stdout], [], [], 8)
                self.assertTrue(ready, "No GUI readiness record")
                record = json.loads(process.stdout.readline())
                self.assertEqual(record["event"], "gui.ready", record)
                with urllib.request.urlopen(record["result"]["url"] + "/api/targets", timeout=2) as response:
                    self.assertTrue(json.load(response)["ok"])
                busy = subprocess.run(args, capture_output=True, timeout=8)
                self.assertEqual(busy.returncode, 1)
                self.assertEqual(json.loads(busy.stdout)["error"]["code"], "GUI_PORT_UNAVAILABLE")
                process.send_signal(signal.SIGINT)
                out, err = process.communicate(timeout=8)
                self.assertIn(process.returncode, (0, 130), err.decode())
                self.assertNotIn(b"Traceback", err)
            finally:
                if process.poll() is None: process.kill()
                process.communicate(timeout=3)
