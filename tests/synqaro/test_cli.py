"""Canonical application CLI works without optional web dependencies."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class CliTests(unittest.TestCase):
    def run_cli(self, *args, module='synqaro'):
        return subprocess.run([sys.executable, '-S', '-m', module, *args],
            env={**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[2] / 'src')},
            capture_output=True, text=True, timeout=10)

    def test_help_and_invalid_port_without_optional_packages(self):
        for args in [('--help',), ('gui', '--help')]:
            result = self.run_cli(*args)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('synqaro', result.stdout)
        result = self.run_cli('--json', 'gui', '--port', '0')
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(json.loads(result.stdout)['error']['code'], 'INVALID_USAGE')

    def test_missing_web_packages_preserves_config_in_recovery_command(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / 'custom inventory.json'
            config.write_text('{"version":1,"instances":[]}\n')
            config.chmod(0o600)
            result = self.run_cli('--json', '--config', str(config), 'gui', '--no-browser')
            self.assertEqual(result.returncode, 1, result.stderr)
            error = json.loads(result.stdout)['error']
            self.assertEqual(error['code'], 'WEB_EXTRA_REQUIRED')
            self.assertIn(['synqaro', '--config', str(config), 'gui'], error['actions'])

    def test_legacy_alias_forwards_errors_and_warns_only_on_stderr(self):
        result = self.run_cli('--json', 'gui', '--port', '0', module='simquaro')
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)['error']['code'], 'INVALID_USAGE')
        self.assertIn('synqaro gui', result.stderr)
        self.assertIn('deprecated', result.stderr)
