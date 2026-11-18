"""Mandatory real-browser acceptance using actual HTTP and simulator TCP."""

from dataclasses import replace
import json
import os
import re
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
        self.server = subprocess.Popen([sys.executable,"-m","synqaro","--json","--config",str(self.store.path),
            "gui","--port",str(port),"--no-browser"], stdout=subprocess.PIPE, stderr=self.server_log,
            env={**os.environ, "XDG_RUNTIME_DIR": self.temp.name})
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
        expect(self.page.get_by_role("heading", name="Synqaro — Hardware Console", exact=True)).to_be_visible()

    def test_management_controls_and_workspace_heading_align(self):
        target = self.page.locator('#target').bounding_box()
        for name in ('start', 'stop', 'restart', 'refresh-admin'):
            bounds = self.page.locator('#' + name).bounding_box()
            self.assertAlmostEqual(bounds['y'], target['y'], delta=1)
            self.assertAlmostEqual(bounds['height'], target['height'], delta=1)
        heading = self.page.get_by_role('heading', name='Workspace', exact=True)
        expect(heading).to_be_visible()
        self.assertAlmostEqual(heading.bounding_box()['x'],
            self.page.locator('#management-title').bounding_box()['x'], delta=1)

    def test_workspace_buttons_select_exclusively_and_keep_summary_concise(self):
        buttons = self.page.get_by_role('group', name='Workspace selection').get_by_role('button')
        expect(buttons).to_have_count(3)
        for button in buttons.all():
            expect(button).to_have_attribute('aria-pressed', 'false')
        self.page.locator('#start').click()
        expect(self.page.locator('#management-status')).to_have_text(
            '✓ receiver-a: running · 1 simulator running, started by this GUI', timeout=8000)
        self.page.screenshot(path='/tmp/synqaro-layout-overview.png', full_page=True)
        for name, panel in [('Communication', 'console'), ('Test', 'tests'), ('Configuration', 'configuration')]:
            button = self.page.get_by_role('button', name=name, exact=True)
            button.focus()
            button.press('Enter')
            expect(button).to_have_attribute('aria-pressed', 'true')
            expect(self.page.locator('[data-workspace][aria-pressed="true"]')).to_have_count(1)
            expect(self.page.locator('#' + panel)).to_be_visible()
        expect(self.page.locator('footer')).to_have_text('Closing this page keeps simulators and connections active.')
        self.assertLess(self.page.locator('footer').evaluate('(e) => parseFloat(getComputedStyle(e).fontSize)'),
            self.page.locator('#management-status').evaluate('(e) => parseFloat(getComputedStyle(e).fontSize)'))
        self.page.screenshot(path='/tmp/synqaro-layout-desktop.png', full_page=True)

    def test_collapsed_console_preserves_connection_and_guided_operations(self):
        self.start_and_connect()
        console = self.page.locator('#console')
        expect(console).to_have_js_property('open', False)
        expect(self.page.locator('#wire-log')).not_to_be_visible()
        expect(self.page.locator('#connect')).to_be_visible()
        expect(self.page.locator('#disconnect')).to_be_visible()
        expect(self.page.locator('#connection-state')).to_be_visible()
        expect(self.page.get_by_label('Console mode', exact=True)).to_be_visible()
        self.assertGreater(console.bounding_box()['y'], self.page.locator('#control').bounding_box()['y'])
        self.page.get_by_role('button', name='Read frequency', exact=True).click()
        expect(self.page.locator('#response')).to_contain_text('sampled_at')
        self.page.locator('#console > summary').click()
        expect(self.page.locator('#wire-log')).to_be_visible()
        sid = self.page.evaluate('session.id')
        evidence = self.page.locator('#wire-log').inner_text()
        self.page.locator('#console > summary').click()
        self.page.get_by_role('button', name='Read receiver status', exact=True).click()
        expect(self.page.locator('#response')).to_contain_text('health')
        self.assertEqual(self.page.evaluate('session.id'), sid)
        self.page.locator('#console > summary').click()
        expect(self.page.locator('#wire-log')).to_contain_text(evidence)
        self.page.locator('#console > summary').click()
        self.page.screenshot(path='/tmp/synqaro-operations-first.png', full_page=True)
        self.page.set_viewport_size({'width': 390, 'height': 844})
        self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'), 390)
        self.assertGreater(console.bounding_box()['y'], self.page.locator('#control').bounding_box()['y'])
        self.page.screenshot(path='/tmp/synqaro-operations-narrow.png', full_page=True)
        self.page.get_by_role('button', name='Test', exact=True).click()
        expect(self.page.locator('#connection')).not_to_be_visible()
        expect(console).not_to_be_visible()
        self.page.get_by_role('button', name='Communication', exact=True).click()
        expect(self.page.locator('#connection-state')).to_contain_text(re.compile('^connected'))
        self.page.get_by_role('button', name='Disconnect', exact=True).click()
        expect(self.page.locator('#connection-state')).to_contain_text(re.compile('^disconnected'))

    def test_running_counts_distinguish_cli_instances_and_hide_zero_external(self):
        external = subprocess.Popen([sys.executable, '-m', 'simquaro', '--json',
            '--config', str(self.store.path), 'start', 'receiver-b'],
            stdout=subprocess.PIPE, stderr=self.server_log,
            env={**os.environ, 'XDG_RUNTIME_DIR': self.temp.name})
        def stop_external():
            if external.poll() is None:
                external.send_signal(signal.SIGINT)
            external.communicate(timeout=8)
        self.addCleanup(stop_external)
        ready, _, _ = select.select([external.stdout], [], [], 8)
        self.assertTrue(ready, 'External simulator did not report startup')
        record = json.loads(external.stdout.readline())
        self.assertTrue(record['result']['ok'], record)
        status = self.page.locator('#management-status')
        expect(status).to_contain_text('0 simulators running, started by this GUI')
        expect(status).to_contain_text('1 simulator running, started externally', timeout=8000)
        self.page.locator('#start').click()
        expect(status).to_contain_text('1 simulator running, started by this GUI', timeout=8000)
        expect(status).to_contain_text('1 simulator running, started externally')
        stop_external()
        expect(status).not_to_contain_text('started externally', timeout=8000)

    def test_management_panels_all_and_reopening_preserve_server_connections(self):
        expect(self.page.locator('#console')).not_to_be_visible()
        expect(self.page.locator('#tests')).not_to_be_visible()
        expect(self.page.locator('#configuration')).not_to_be_visible()
        self.page.get_by_label('Target simulator', exact=True).select_option('all')
        self.page.get_by_role('button', name='Start', exact=True).click()
        expect(self.page.locator('#management-status')).to_contain_text('2 simulators running, started by this GUI', timeout=10000)
        self.page.get_by_role("button", name="Communication", exact=True).click()
        expect(self.page.locator('#console')).to_be_visible()
        expect(self.page.locator('#tests')).not_to_be_visible()
        self.page.get_by_label('Communication target', exact=True).select_option('receiver-a')
        self.page.get_by_role('button', name='Connect', exact=True).click()
        expect(self.page.locator('#connection-state')).to_contain_text(re.compile("^connected"))
        sid = self.page.evaluate('session.id')
        self.page.close()
        self.page = self.context.new_page()
        self.page.goto(self.url)
        expect(self.page.locator('#management-status')).to_contain_text('2 simulators running, started by this GUI', timeout=8000)
        self.page.get_by_role("button", name="Communication", exact=True).click()
        expect(self.page.locator('#connection-state')).to_contain_text(re.compile("^connected"))
        self.assertEqual(self.page.evaluate('session.id'), sid)
        self.page.get_by_role("button", name="Configuration", exact=True).click()
        expect(self.page.locator('#console')).not_to_be_visible()
        self.page.get_by_label('Initial frequency (GHz)', exact=True).fill('6')
        self.page.get_by_role('button', name='Refresh', exact=True).click()
        expect(self.page.get_by_label('Initial frequency (GHz)', exact=True)).to_have_value('6')
        self.page.get_by_role("button", name="Test", exact=True).click()
        expect(self.page.locator('#tests')).to_be_visible()
        expect(self.page.locator('#configuration')).not_to_be_visible()
        self.page.get_by_label('Target type', exact=True).select_option('hardware')
        expect(self.page.get_by_label('Target hardware', exact=True)).to_have_value('physical-c')
        expect(self.page.get_by_role('button', name='Start', exact=True)).not_to_be_visible()
        self.page.get_by_label('Target hardware', exact=True).select_option('all')
        self.page.locator('#start').click()
        expect(self.page.locator('#management-status')).to_contain_text('1 failed', timeout=8000)
        self.page.get_by_text('Details', exact=True).click()
        expect(self.page.locator('#management-details')).to_contain_text('physical-c')
        self.page.screenshot(path='/tmp/synqaro-management-hardware.png', full_page=True)

    def test_inventory_reload_refreshes_editor_with_revision(self):
        self.page.get_by_role("button", name="Configuration", exact=True).click()
        snapshot = self.store.load()
        entry = snapshot.entries['receiver-a']
        entries = dict(snapshot.entries)
        entries['receiver-a'] = replace(entry, config=replace(entry.config,
            settings=replace(entry.config.settings, initial_frequency=7)))
        self.store.save(entries, expected_revision=snapshot.revision)
        self.page.get_by_role('button', name='Reload inventory', exact=True).click()
        expect(self.page.get_by_label('Initial frequency (GHz)', exact=True)).to_have_value('7')

    def test_hardware_console_remains_available_after_mode_disconnect(self):
        self.start_and_connect()
        snapshot = self.store.load()
        entries = dict(snapshot.entries)
        entries['physical-c'] = replace(entries['physical-c'], config=replace(
            entries['physical-c'].config, port=entries['receiver-a'].config.port))
        entries['receiver-a'] = replace(entries['receiver-a'], config=replace(
            entries['receiver-a'].config, port=free_port()))
        self.store.save(entries, expected_revision=snapshot.revision)
        self.page.get_by_label('Target type', exact=True).select_option('hardware')
        self.page.locator('#start').click()
        expect(self.page.locator('#management-status')).to_contain_text('1/1 connected', timeout=8000)
        expect(self.page.locator('#console')).to_be_visible()
        self.page.get_by_label('Console mode', exact=True).select_option('raw')
        expect(self.page.locator('#management-status')).to_contain_text('0/1 connected', timeout=8000)
        expect(self.page.locator('#console')).to_be_visible()
        self.page.locator('#connect').click()
        expect(self.page.locator('#connection-state')).to_contain_text('connected · raw')

    def stop_server(self):
        if self.server.poll() is None: self.server.send_signal(signal.SIGINT)
        try: self.server.communicate(timeout=8)
        except subprocess.TimeoutExpired:
            self.server.kill()
            self.server.communicate(timeout=3)

    def start_and_connect(self):
        self.page.get_by_role("button", name="Start", exact=True).click()
        expect(self.page.locator("#management-status")).to_contain_text("1 simulator running, started by this GUI", timeout=8000)
        self.page.get_by_role("button", name="Communication", exact=True).click()
        self.page.get_by_role("button", name="Connect", exact=True).click()
        expect(self.page.locator("#connection-state")).to_contain_text(re.compile("^connected"))
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
        other.get_by_label("Target simulator", exact=True).select_option("receiver-b")
        other.get_by_role("button", name="Start", exact=True).click()
        expect(other.locator("#management-status")).to_contain_text("2 simulators running, started by this GUI", timeout=8000)
        other.get_by_role("button", name="Communication", exact=True).click()
        other.get_by_role("button", name="Connect", exact=True).click()
        expect(other.locator("#connection-state")).to_contain_text(re.compile("^connected"))
        expect(self.page.locator("#connection-state")).to_contain_text(re.compile("^connected"))
        self.assertEqual(self.page.get_by_label("Console mode", exact=True).count(), 1,
                         self.page.locator("label").all_text_contents())
        self.page.get_by_label("Console mode", exact=True).select_option("raw")
        expect(self.page.locator("#connection-state")).to_contain_text("disconnected")
        self.page.get_by_role("button", name="Connect", exact=True).click()
        self.page.locator('#console > summary').click()
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
        self.page.get_by_role("button", name="Test", exact=True).click()
        self.page.get_by_label("Allow changes for this run", exact=False).check()
        self.page.once("dialog", lambda dialog: dialog.accept())
        self.page.get_by_role("button", name="Run checks", exact=True).click()
        expect(self.page.locator("#test-report")).to_contain_text('"passed": 10', timeout=15000)
        self.page.get_by_role("button", name="Stop", exact=True).click()
        expect(self.page.locator("#management-status")).to_contain_text("0 simulators running, started by this GUI", timeout=8000)
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

    def test_saved_header_and_connection_details_track_single_and_other_tab_saves(self):
        self.start_and_connect()
        endpoint = self.snapshot.entries["receiver-b"].config.port
        other = self.context.new_page()
        other.goto(self.url)
        other.get_by_label("Target simulator", exact=True).select_option("receiver-b")
        other.get_by_role("button", name="Start", exact=True).click()
        expect(other.locator("#management-status")).to_contain_text("2 simulators running, started by this GUI", timeout=8000)
        other.get_by_role("button", name="Configuration", exact=True).click()
        self.page.get_by_role("button", name="Configuration", exact=True).click()
        # This page saves a new endpoint and configured identity for receiver-a.
        self.page.get_by_label("Saved TCP port", exact=True).fill(str(endpoint))
        self.page.get_by_label("Expected hardware identity", exact=True).fill("saved-identity-two")
        # Keep inventory endpoints unique by moving receiver-b's saved port first;
        # its already-running process stays at the original endpoint.
        other.get_by_label("Saved TCP port", exact=True).fill(str(free_port()))
        other.get_by_role("button", name="Save configuration", exact=True).click()
        expect(other.locator("#config-state")).to_contain_text("Pending")
        self.page.get_by_role("button", name="Reload saved configuration", exact=True).click()
        self.page.get_by_label("Saved TCP port", exact=True).fill(str(endpoint))
        self.page.get_by_label("Expected hardware identity", exact=True).fill("saved-identity-two")
        self.page.get_by_role("button", name="Save configuration", exact=True).click()
        expect(self.page.get_by_label("Saved TCP port", exact=True)).to_have_value(str(endpoint))
        expect(self.page.get_by_label("Expected hardware identity", exact=True)).to_have_value("saved-identity-two")
        self.page.get_by_role("button", name="Communication", exact=True).click()
        self.page.get_by_label("Console mode", exact=True).select_option("raw")
        self.page.get_by_role("button", name="Connect", exact=True).click()
        expect(self.page.locator("#session-revision")).to_contain_text(f"127.0.0.1:{endpoint}")
        expect(self.page.locator("#session-revision")).to_contain_text("saved-identity-two")
        self.page.get_by_role("button", name="Disconnect", exact=True).click()
        # Other tab changes identity; this page must show the snapshot actually
        # used by Connect, not its stale editor/header.
        other.get_by_label("Target simulator", exact=True).select_option("receiver-a")
        other.get_by_role("button", name="Reload saved configuration", exact=True).click()
        other.get_by_label("Expected hardware identity", exact=True).fill("saved-identity-three")
        other.get_by_role("button", name="Save configuration", exact=True).click()
        expect(other.get_by_label("Expected hardware identity", exact=True)).to_have_value("saved-identity-three")
        self.page.get_by_role("button", name="Connect", exact=True).click()
        expect(self.page.locator("#session-revision")).to_contain_text("saved-identity-three")
        self.assertEqual(self.errors, [])

    def test_finished_job_observation_does_not_replace_an_unsaved_editor_draft(self):
        self.start_and_connect()
        self.page.get_by_role("button", name="Configuration", exact=True).click()
        self.page.get_by_label("Initial frequency (GHz)", exact=True).fill("6")
        self.page.get_by_role("button", name="Stop", exact=True).click()
        expect(self.page.locator("#management-status")).to_contain_text("0 simulators running, started by this GUI", timeout=8000)
        expect(self.page.get_by_label("Initial frequency (GHz)", exact=True)).to_have_value("6")

    def test_configuration_save_apply_and_read_only_checks(self):
        self.start_and_connect()
        self.page.get_by_role("button", name="Configuration", exact=True).click()
        self.page.get_by_label("Initial frequency (GHz)", exact=True).fill("6")
        self.page.get_by_role("button", name="Save configuration", exact=True).click()
        expect(self.page.locator("#config-state")).to_contain_text("Pending")
        self.page.once("dialog", lambda dialog: dialog.accept())
        self.page.get_by_role("button", name="Apply saved settings", exact=True).click()
        expect(self.page.locator("#job-state")).to_contain_text("apply: succeeded", timeout=8000)
        expect(self.page.locator("#config-state")).to_contain_text("In sync")
        self.page.get_by_role("button", name="Test", exact=True).click()
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
        self.assertEqual(self.page.get_by_label("Target simulator", exact=True).count(), 1,
                         self.page.locator("label").all_text_contents())
        self.page.get_by_label("Target type", exact=True).select_option("hardware")
        expect(self.page.get_by_role("button", name="Start", exact=True)).not_to_be_visible()
        expect(self.page.locator("#workspace-empty")).to_be_visible()
        self.page.set_viewport_size({"width":390,"height":844})
        self.page.screenshot(path="/tmp/simquaro-gui-narrow.png", full_page=True)
        overflowing = self.page.evaluate("""Array.from(document.querySelectorAll('*')).filter(e =>
            e.getBoundingClientRect().right > innerWidth + 1).map(e => ({tag:e.tagName,id:e.id,
            right:e.getBoundingClientRect().right,width:e.getBoundingClientRect().width})).slice(0,20)""")
        self.assertLessEqual(self.page.evaluate("document.documentElement.scrollWidth"), 390,
            {"overflow":overflowing, "viewport":self.page.viewport_size,
             "widths":self.page.evaluate("({inner:innerWidth,client:document.documentElement.clientWidth,scrollX:scrollX,body:document.body.scrollWidth})")})
        self.assertEqual(self.errors, [])
