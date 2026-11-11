"""Acceptance tests for shell installers; every write stays inside a temp home.

Breaks caught: help with side effects; unsafe destination deletion; treating an
unrelated launcher as ours; deleting config by default; no --purge confirmation;
editable rather than independent install; failed reinstallation breaking the old
launcher. Integration uses real venv/pip/package entry points, not a pip mock.
Run the opt-in network test with SYNQARO_REAL_INSTALL_TEST=1 and
python -m unittest tests.test_installation -v.
"""

import os
from pathlib import Path
import pty
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request


REPO = Path(__file__).resolve().parents[1]
ROOT = Path(tempfile.gettempdir())
PYTHON = REPO / '.venv/bin/python'
if not PYTHON.is_file():
    PYTHON = Path(sys.executable)


@unittest.skipUnless(sys.platform.startswith('linux'), 'Linux shell installers')
class Scripts(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='case-', dir=ROOT)
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name) / 'user home'
        self.home.mkdir()
        self.env = os.environ.copy()
        # Scoped to subprocesses only: never change the actual session home.
        self.env.update(HOME=str(self.home), XDG_DATA_HOME='', XDG_CONFIG_HOME='')
        self.env.pop('PYTHONPATH', None)
        self.env.pop('PYTHONHOME', None)
        self.prefix = self.home / '.local/share/synqaro'
        self.launcher = self.home / '.local/bin/simquaro'
        self.config = self.home / '.config/simquaro/instances.json'

    def run_script(self, script, *args, env=None, source=REPO):
        return subprocess.run(['bash', str(source / script), *map(str, args)],
                              cwd=ROOT, env=env or self.env, input='',
                              text=True, capture_output=True, timeout=180)

    def test_help_succeeds_without_creating_any_files(self):
        for script in ('install.sh', 'uninstall.sh'):
            with self.subTest(script=script):
                result = self.run_script(script, '--help')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('Usage:', result.stdout)
        self.assertEqual(list(self.home.iterdir()), [])

    def test_unknown_option_refuses_without_writes(self):
        for script in ('install.sh', 'uninstall.sh'):
            result = self.run_script(script, '--not-an-option')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('--help', result.stderr)
        self.assertEqual(list(self.home.iterdir()), [])

    def test_missing_python_reports_how_to_retry_without_writes(self):
        result = self.run_script('install.sh', '--python', '/missing/python')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Python', result.stderr)
        self.assertIn('--python', result.stderr)
        self.assertFalse(self.prefix.exists())
        self.assertFalse(self.launcher.exists())

    def test_foreign_prefix_is_never_removed(self):
        self.prefix.mkdir(parents=True)
        precious = self.prefix / 'unrelated.txt'
        precious.write_text('keep me')
        for script in ('install.sh', 'uninstall.sh'):
            result = self.run_script(script)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(precious.read_text(), 'keep me')

    def test_symlink_prefix_is_never_followed(self):
        target = self.home / 'other application'
        target.mkdir()
        self.prefix.parent.mkdir(parents=True)
        self.prefix.symlink_to(target)
        for script in ('install.sh', 'uninstall.sh'):
            result = self.run_script(script)
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(self.prefix.is_symlink())
            self.assertTrue(target.exists())

    def test_home_is_rejected_as_prefix(self):
        for script in ('install.sh', 'uninstall.sh'):
            result = self.run_script(script, '--prefix', self.home)
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(self.home.is_dir())

    def test_foreign_launcher_is_not_replaced(self):
        self.launcher.parent.mkdir(parents=True)
        self.launcher.write_text('another application')
        result = self.run_script('install.sh', '--python', PYTHON)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.launcher.read_text(), 'another application')
        self.assertFalse(self.prefix.exists())

    def test_uninstall_missing_install_is_idempotent_and_preserves_config(self):
        self.config.parent.mkdir(parents=True)
        self.config.write_text('user settings')
        for _ in range(2):
            result = self.run_script('uninstall.sh')
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.config.read_text(), 'user settings')

    def test_noninteractive_purge_requires_yes_without_side_effects(self):
        self.config.parent.mkdir(parents=True)
        self.config.write_text('user settings')
        result = self.run_script('uninstall.sh', '--purge')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('--yes', result.stderr)
        self.assertEqual(self.config.read_text(), 'user settings')

    def test_purge_removes_only_managed_config_and_does_not_follow_references(self):
        self.config.parent.mkdir(parents=True)
        external = self.home / 'external.json'
        external.write_text('external settings')
        self.config.write_text('{"external": "' + str(external) + '"}')
        self.config.with_name('instances.json.lock').touch()
        other = self.config.parent / 'notes.txt'
        other.write_text('unrelated')
        result = self.run_script('uninstall.sh', '--purge', '--yes')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.config.exists())
        self.assertFalse(self.config.with_name('instances.json.lock').exists())
        self.assertEqual(external.read_text(), 'external settings')
        self.assertEqual(other.read_text(), 'unrelated')

    def test_purge_refuses_symlink_config_directory(self):
        external = self.home / 'external config'
        external.mkdir()
        precious = external / 'instances.json'
        precious.write_text('keep')
        self.config.parent.parent.mkdir(parents=True)
        self.config.parent.symlink_to(external)
        result = self.run_script('uninstall.sh', '--purge', '--yes')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(precious.read_text(), 'keep')

    def fixture_installation(self):
        self.prefix.mkdir(parents=True)
        marker = self.prefix / '.synqaro-installation'
        marker.write_text('synqaro-install-v1\n' + str(self.prefix) + '\n' +
                          str(self.launcher) + '\n' + str(self.config.parent) + '\n')
        return marker

    def test_purge_refuses_changed_ancestor_symlink(self):
        self.fixture_installation()
        external = self.home / 'external config'
        (external / 'simquaro').mkdir(parents=True)
        precious = external / 'simquaro/instances.json'
        precious.write_text('external settings')
        (self.home / '.config').symlink_to(external)
        result = self.run_script('uninstall.sh', '--purge', '--yes')
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(precious.read_text(), 'external settings')
        self.assertTrue(self.prefix.exists())

    def test_interruption_during_bootstrap_is_retryable(self):
        probe = subprocess.run([str(PYTHON), '-I', '-c', 'import venv, ensurepip'],
                               capture_output=True)
        if probe.returncode:
            self.skipTest('An interpreter with venv/ensurepip is needed for bootstrap')
        tools = self.home / 'fault tools'
        tools.mkdir()
        (tools / 'flock').write_text('#!/usr/bin/env bash\nkill -KILL "$PPID"\n')
        (tools / 'flock').chmod(0o700)
        result = self.run_script('install.sh', '--python', PYTHON,
                                 env={**self.env, 'PATH': str(tools) + ':' + self.env['PATH']})
        self.assertEqual(result.returncode, -9, result.stdout + result.stderr)
        result = self.run_script('install.sh', '--python', '/missing/python')
        self.assertIn('Python', result.stderr,
                      'retry must get past prefix validation, not reject its own interrupted bootstrap')

    def test_interrupted_removal_is_retryable(self):
        self.fixture_installation()
        (self.prefix / 'payload').write_text('installed code')
        tools = self.home / 'fault tools'
        tools.mkdir()
        (tools / 'rm').write_text(
            '#!/usr/bin/env bash\ntarget=${!#}\n'
            'if [[ -f "$target/.synqaro-installation" ]]; then\n'
            '    /bin/rm -- "$target/.synqaro-installation"\nfi\nexit 1\n')
        (tools / 'rm').chmod(0o700)
        self.run_script('uninstall.sh',
                        env={**self.env, 'PATH': str(tools) + ':' + self.env['PATH']})
        result = self.run_script('uninstall.sh')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(self.prefix.exists())

    def test_lock_alias_does_not_truncate_external_data(self):
        self.fixture_installation()
        precious = self.home / 'external user data'
        precious.write_text('do not truncate')
        os.link(precious, self.prefix / '.maintenance.lock')
        result = self.run_script('uninstall.sh')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(precious.read_text(), 'do not truncate')

    def test_interactive_purge_can_be_cancelled_then_confirmed(self):
        self.fixture_installation()
        self.config.parent.mkdir(parents=True)
        self.config.write_text('user settings')
        for answer in (b'no\n', b'yes\n'):
            master, slave = pty.openpty()
            try:
                process = subprocess.Popen(['bash', str(REPO / 'uninstall.sh'), '--purge'],
                                           stdin=slave, stdout=subprocess.PIPE,
                                           stderr=subprocess.PIPE, env=self.env, text=True)
                os.close(slave)
                slave = None
                os.write(master, answer)
                stdout, stderr = process.communicate(timeout=10)
                self.assertEqual(process.returncode, 0, stdout + stderr)
                self.assertEqual(self.config.exists(), answer == b'no\n')
                self.assertEqual(self.prefix.exists(), answer == b'no\n')
            finally:
                os.close(master)
                if slave is not None:
                    os.close(slave)

    @unittest.skipUnless(os.environ.get('SYNQARO_REAL_INSTALL_TEST') == '1',
                         'enable explicitly for real pip/venv installation')
    def test_real_install_reinstall_and_removal(self):
        source = self.home / 'downloaded archive'
        source.mkdir()
        shutil.copy(REPO / 'pyproject.toml', source)
        shutil.copy(REPO / 'install.sh', source)
        shutil.copytree(REPO / 'src', source / 'src',
                        ignore=shutil.ignore_patterns('__pycache__', '*.egg-info'))
        self.config.parent.mkdir(parents=True)
        self.config.write_text('existing user settings')
        escaped_target = self.home / 'pip external target'
        unsafe_pip = {**self.env, 'PIP_TARGET': str(escaped_target)}
        result = self.run_script('install.sh', '--python', PYTHON,
                                 source=source, env=unsafe_pip)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(escaped_target.exists(), 'pip must stay inside its private environment')
        self.assertTrue(self.launcher.is_symlink())
        self.assertEqual(self.config.read_text(), 'existing user settings')
        shutil.rmtree(source)
        result = subprocess.run([str(self.launcher), '--help'], env=self.env,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('gui', result.stdout)
        # Launch the installed GUI with current resolved dependencies, its
        # packaged static files, and a private runtime; never start a simulator.
        gui_config = self.home / 'gui-config.json'
        gui_config.write_text('{"version":1,"instances":[]}\n')
        gui_config.chmod(0o600)
        runtime = self.home / 'runtime'
        runtime.mkdir(mode=0o700)
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        gui = subprocess.Popen([str(self.launcher), '--config', str(gui_config),
                                'gui', '--no-browser', '--port', str(port)],
                               env={**self.env, 'XDG_RUNTIME_DIR': str(runtime)},
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            deadline = time.monotonic() + 10
            while True:
                try:
                    with opener.open(f'http://127.0.0.1:{port}/', timeout=1) as response:
                        self.assertIn(b'Hardware workbench', response.read())
                    with opener.open(f'http://127.0.0.1:{port}/static/app.js', timeout=1) as response:
                        self.assertEqual(response.status, 200)
                    break
                except (urllib.error.URLError, TimeoutError):
                    if time.monotonic() >= deadline or gui.poll() is not None:
                        self.fail('Installed GUI did not become ready')
                    time.sleep(.05)
        finally:
            gui.terminate()
            output, errors = gui.communicate(timeout=10)
            self.assertIn(gui.returncode, (0, -15), output + errors)
        target = self.launcher.resolve()
        # A failed dependency installation must leave the old launcher usable.
        broken_env = {**self.env, 'PIP_NO_INDEX': '1',
                      'PIP_FIND_LINKS': str(self.home / 'no wheels'),
                      'PIP_CACHE_DIR': str(self.home / 'empty cache')}
        result = self.run_script('install.sh', '--python', PYTHON, env=broken_env)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.launcher.resolve(), target)
        result = subprocess.run([str(self.launcher), '--help'], env=self.env,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.run_script('install.sh', '--python', PYTHON)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        # Refuse removal while this installation still runs a Python process.
        python = self.prefix / 'current/bin/python'
        process = subprocess.Popen([str(python), '-c', 'import time; time.sleep(60)'],
                                   env=self.env)
        try:
            result = self.run_script('uninstall.sh')
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(self.launcher.exists())
        finally:
            process.terminate()
            process.wait(timeout=5)
        result = self.run_script('uninstall.sh')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(self.prefix.exists())
        self.assertFalse(self.launcher.is_symlink())
        self.assertEqual(self.config.read_text(), 'existing user settings')
        result = self.run_script('uninstall.sh', '--purge', '--yes')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(self.config.exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
