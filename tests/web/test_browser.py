"""Mandatory real-browser acceptance using actual HTTP and simulator TCP."""

from dataclasses import replace
import json
from pathlib import Path
import select
import signal
import socket
import subprocess
import sys
import tempfile
import unittest

from playwright.sync_api import sync_playwright, expect

from simquaro.configuration import ConfigStore, InventoryEntry


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class BrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        # Real installed Chrome, isolated test contexts, normal Chromium sandbox.
        cls.browser = cls.playwright.chromium.launch(channel="chrome", headless=True, chromium_sandbox=True)

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "browser"): cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="sq-browser-")
        self.addCleanup(self.temp.cleanup)
        self.store = ConfigStore(Path(self.temp.name) / "instances.json")
        snapshot = self.store.initialize()
        entry = snapshot.entries["receiver-a"]
        settings = replace(entry.config.settings, tuning_duration_ms=10, stop_duration_ms=10,
                           calibrate_preparation_ms=100, calibrate_measurement_ms=200, calibrate_finalization_ms=100)
        first = replace(entry, config=replace(entry.config, settings=settings, port=free_port()))
        second = replace(first, config=replace(first.config, name="receiver-b", port=free_port()))
        physical = InventoryEntry(replace(first.config, name="physical-c", port=1), "hardware")
        self.snapshot = self.store.save({"receiver-a":first,"receiver-b":second,"physical-c":physical}, expected_revision=snapshot.revision)
        port = free_port()
        self.server_log = tempfile.TemporaryFile()
        self.addCleanup(self.server_log.close)
        self.server = subprocess.Popen([sys.executable,"-m","simquaro","--json","--config",str(self.store.path),
            "gui","--port",str(port),"--no-browser"], stdout=subprocess.PIPE, stderr=self.server_log)
        self.addCleanup(self.stop_server)
        ready, _, _ = select.select([self.server.stdout], [], [], 8)
        self.assertTrue(ready, "GUI did not report ready")
        record = json.loads(self.server.stdout.readline())
        self.assertEqual(record["event"], "gui.ready", record)
        self.url = record["result"]["url"]
        self.context = self.browser.new_context(viewport={"width":1280,"height":950})
        self.addCleanup(self.context.close)
        self.page = self.context.new_page()
        self.errors = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.page.goto(self.url)
        expect(self.page.get_by_role("heading", name="Simquaro", exact=True)).to_be_visible()

    def stop_server(self):
        if self.server.poll() is None: self.server.send_signal(signal.SIGINT)
        try: self.server.communicate(timeout=8)
        except subprocess.TimeoutExpired:
            self.server.kill()
            self.server.communicate(timeout=3)

    def start_and_connect(self):
        self.page.get_by_role("button", name="Start simulator", exact=True).click()
        expect(self.page.locator("#job-state")).to_contain_text("succeeded", timeout=8000)
        self.page.get_by_role("button", name="Connect", exact=True).click()
        expect(self.page.locator("#connection-state")).to_contain_text("connected")
        self.assertEqual(self.page.get_by_label("Console mode", exact=True).count(), 1,
                         self.page.locator("label").all_text_contents())

    def test_guided_operations_raw_errors_and_independent_tabs(self):
        self.start_and_connect()
        self.page.get_by_label("Frequency (GHz)", exact=True).fill("5.1234565")
        self.page.get_by_role("button", name="Set frequency", exact=True).click()
        expect(self.page.locator("#response")).to_contain_text("5.123457")
        self.page.get_by_role("button", name="Read frequency", exact=True).click()
        expect(self.page.locator("#response")).to_contain_text("sampled_at")
        self.page.get_by_role("button", name="Run calibrate", exact=True).click()
        expect(self.page.locator("#response")).to_contain_text("accepted")
        self.page.get_by_role("button", name="Read procedure status", exact=True).click()
        expect(self.page.locator("#response")).to_contain_text("calibrate")
        other = self.context.new_page()
        other.goto(self.url)
        other.get_by_label("Target", exact=True).select_option("receiver-b")
        other.get_by_role("button", name="Start simulator", exact=True).click()
        expect(other.locator("#job-state")).to_contain_text("succeeded", timeout=8000)
        other.get_by_role("button", name="Connect", exact=True).click()
        expect(other.locator("#connection-state")).to_contain_text("connected")
        expect(self.page.locator("#connection-state")).to_contain_text("connected")
        self.assertEqual(self.page.get_by_label("Console mode", exact=True).count(), 1,
                         self.page.locator("label").all_text_contents())
        self.page.get_by_label("Console mode", exact=True).select_option("raw")
        expect(self.page.locator("#connection-state")).to_contain_text("disconnected")
        self.page.get_by_role("button", name="Connect", exact=True).click()
        self.page.get_by_label("Literal request", exact=True).fill(r"#nonsense <id=77>\n")
        self.page.get_by_role("button", name="Send literal request", exact=True).click()
        expect(self.page.locator("#wire-log")).to_contain_text(r"#error <id=77>: code=UNKNOWN_VERB", timeout=5000)
        self.assertEqual(self.errors, [])

    def test_scan_cancel_reboot_and_explicit_modifying_suite(self):
        self.start_and_connect()
        self.page.get_by_text("Scan settings", exact=True).click()
        self.page.get_by_role("button", name="Run scan", exact=True).click()
        expect(self.page.locator("#response")).to_contain_text("accepted")
        self.page.get_by_role("button", name="Read procedure status", exact=True).click()
        expect(self.page.locator("#response")).to_contain_text("running")
        self.page.get_by_role("button", name="Cancel procedure", exact=True).click()
        expect(self.page.locator("#response")).to_contain_text("accepted")
        self.page.get_by_role("button", name="Read procedure status", exact=True).click()
        expect(self.page.locator("#response")).to_contain_text("cancelled")
        self.page.once("dialog", lambda dialog: dialog.accept())
        self.page.get_by_role("button", name="Reboot hardware", exact=True).click()
        expect(self.page.locator("#response")).to_contain_text("accepted")
        self.page.get_by_role("button", name="Disconnect", exact=True).click()
        self.page.get_by_label("Allow changes for this run", exact=False).check()
        self.page.once("dialog", lambda dialog: dialog.accept())
        self.page.get_by_role("button", name="Run checks", exact=True).click()
        expect(self.page.locator("#test-report")).to_contain_text('"passed": 10', timeout=15000)
        self.page.get_by_role("button", name="Stop simulator", exact=True).click()
        expect(self.page.locator("#job-state")).to_contain_text("stop: succeeded", timeout=8000)
        self.assertEqual(self.errors, [])

    def test_scheduled_fault_waits_for_explicit_hardware_request(self):
        self.start_and_connect()
        self.page.get_by_text("Simulator fault injection", exact=True).click()
        self.page.get_by_role("button", name="Refresh faults", exact=True).click()
        self.page.get_by_label("Fault", exact=True).select_option("drop_response")
        self.page.get_by_label("Trigger event", exact=True).select_option("response_ready")
        self.page.get_by_role("button", name="Schedule fault", exact=True).click()
        expect(self.page.locator("#fault-state")).to_contain_text('"remaining": 1')
        for _ in range(3):
            self.page.get_by_role("button", name="Refresh faults", exact=True).click()
            expect(self.page.locator("#fault-state")).to_contain_text('"remaining": 1')
        self.page.get_by_role("button", name="Read receiver status", exact=True).click()
        expect(self.page.locator("#notice")).to_contain_text("RESPONSE_TIMEOUT", timeout=8000)
        self.page.get_by_role("button", name="Refresh faults", exact=True).click()
        expect(self.page.locator("#fault-state")).to_contain_text('"rules": []')
        expect(self.page.locator("#fault-state")).to_contain_text('"command": "status"')
        self.assertEqual(self.errors, [])

    def test_configuration_save_apply_and_read_only_checks(self):
        self.start_and_connect()
        self.page.get_by_label("Initial frequency (GHz)", exact=True).fill("6")
        self.page.get_by_role("button", name="Save configuration", exact=True).click()
        expect(self.page.locator("#config-state")).to_contain_text("Pending")
        self.page.once("dialog", lambda dialog: dialog.accept())
        self.page.get_by_role("button", name="Apply saved settings", exact=True).click()
        expect(self.page.locator("#job-state")).to_contain_text("apply: succeeded", timeout=8000)
        expect(self.page.locator("#config-state")).to_contain_text("In sync")
        expect(self.page.locator("#connection-state")).to_contain_text("disconnected")
        self.page.get_by_role("button", name="Run checks", exact=True).click()
        expect(self.page.locator("#test-report")).to_contain_text('"passed": 5', timeout=8000)
        expect(self.page.locator("#test-report")).to_contain_text('"skipped": 5')
        self.assertEqual(self.store.load().entries["receiver-a"].config.settings.initial_frequency, 6)
        self.page.screenshot(path="/tmp/simquaro-gui-desktop.png", full_page=True)
        self.assertEqual(self.errors, [])

    def test_fault_controls_physical_restrictions_and_narrow_layout(self):
        self.start_and_connect()
        self.page.get_by_text("Simulator fault injection", exact=True).click()
        self.page.get_by_role("button", name="Refresh faults", exact=True).click()
        self.page.get_by_label("Fault", exact=True).select_option("frequency_read_failure")
        self.page.get_by_role("button", name="Activate fault", exact=True).click()
        expect(self.page.locator("#fault-state")).to_contain_text("frequency_read_failure")
        self.page.get_by_role("button", name="Read frequency", exact=True).click()
        expect(self.page.locator("#response")).to_contain_text("FREQUENCY_READ_FAILED")
        self.page.get_by_role("button", name="Clear fault", exact=True).click()
        self.assertEqual(self.page.get_by_label("Target", exact=True).count(), 1,
                         self.page.locator("label").all_text_contents())
        self.page.get_by_label("Target", exact=True).select_option("physical-c")
        expect(self.page.get_by_role("button", name="Start simulator", exact=True)).not_to_be_visible()
        expect(self.page.locator("#response")).to_contain_text("No request sent to physical-c")
        self.page.set_viewport_size({"width":390,"height":844})
        self.page.screenshot(path="/tmp/simquaro-gui-narrow.png", full_page=True)
        overflowing = self.page.evaluate("""Array.from(document.querySelectorAll('*')).filter(e =>
            e.getBoundingClientRect().right > innerWidth + 1).map(e => ({tag:e.tagName,id:e.id,
            right:e.getBoundingClientRect().right,width:e.getBoundingClientRect().width})).slice(0,20)""")
        self.assertLessEqual(self.page.evaluate("document.documentElement.scrollWidth"), 390,
            {"overflow":overflowing, "viewport":self.page.viewport_size,
             "widths":self.page.evaluate("({inner:innerWidth,client:document.documentElement.clientWidth,scrollX:scrollX,body:document.body.scrollWidth})")})
        self.assertEqual(self.errors, [])
