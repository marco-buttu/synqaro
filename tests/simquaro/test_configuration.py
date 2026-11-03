"""Persistent inventory preserves validation, exact values and concurrent saves."""

from dataclasses import replace
import importlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        try: self.module = importlib.import_module("simquaro.configuration")
        except ImportError: self.fail("persistent configuration store is missing")
        self.temp = tempfile.TemporaryDirectory(prefix="sq-config-")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "instances.json"
        self.store = self.module.ConfigStore(self.path)

    def write(self, text):
        self.path.write_text(text)
        self.path.chmod(0o600)

    def example(self, **fields):
        return json.dumps({"version": 1, "instances": [{"name": "receiver-a",
            "model": "fictitious_receiver", "host": "127.0.0.1", "port": 9001,
            "receiver": {"initial_frequency": 5}, **fields}]})

    def test_missing_explicit_path_errors_and_init_is_idempotent(self):
        with self.assertRaises(self.module.ConfigurationError): self.store.load()
        snapshot = self.store.initialize()
        self.assertEqual(snapshot.entries["receiver-a"].config.settings.initial_frequency, 5)
        before = self.path.read_bytes()
        self.assertEqual(self.store.initialize().revision, snapshot.revision)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_implicit_missing_defaults_do_not_create_a_file(self):
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": self.temp.name}):
            snapshot = self.module.ConfigStore().load()
        self.assertEqual(snapshot.source, "builtin")
        self.assertFalse(snapshot.path.exists())
        self.assertEqual(snapshot.entries["receiver-a"].kind, "simulator")

    def test_partial_settings_normalize_and_hardware_requires_explicit_identity(self):
        self.write(self.example())
        snapshot = self.store.load()
        self.assertEqual(snapshot.entries["receiver-a"].config.settings.max_pending_requests, 4)
        self.write(self.example(kind="hardware"))
        with self.assertRaises(self.module.ConfigurationError): self.store.load()
        self.write(self.example(kind="hardware", receiver={"hardware_id": "physical-01"}))
        self.assertEqual(self.store.load().entries["receiver-a"].kind, "hardware")

    def test_duplicate_unknown_and_nonfinite_input_never_falls_back(self):
        examples = ["{}", '{"version":1,"version":1,"instances":[]}',
            self.example(extra=True), self.example(receiver={"wrong": 5}),
            self.example(port=0), self.example(kind="unknown"),
            self.example().replace('"version": 1', '"version": 2'),
            self.example().replace('"initial_frequency": 5', '"initial_frequency": NaN'),
            self.example().replace('"initial_frequency": 5', '"initial_frequency": 5.0000000000000001'),
            " " * (1048576 + 1)]
        for text in examples:
            with self.subTest(text=text[:70]):
                self.write(text)
                with self.assertRaises(self.module.ConfigurationError): self.store.load()

    def test_stale_revision_cannot_overwrite_saved_values(self):
        old = self.store.initialize()
        entry = old.entries["receiver-a"]
        changed = replace(entry, config=replace(entry.config, port=9002))
        fresh = self.store.save({"receiver-a": changed}, expected_revision=old.revision)
        self.assertEqual(fresh.entries["receiver-a"].config.port, 9002)
        with self.assertRaises(self.module.ConfigurationError) as caught:
            self.store.save(old.entries, expected_revision=old.revision)
        self.assertEqual(caught.exception.code, "CONFIG_CONFLICT")
        self.assertEqual(self.store.load().entries["receiver-a"].config.port, 9002)

    def test_failed_replace_preserves_file_and_crash_left_lock_is_reusable(self):
        old = self.store.initialize()
        before = self.path.read_bytes()
        with patch("os.replace", side_effect=OSError("test disk failure")):
            with self.assertRaises(self.module.ConfigurationError):
                self.store.save(old.entries, expected_revision=old.revision)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.store.save(old.entries, expected_revision=old.revision).entries, old.entries)

    def test_symlink_configuration_is_rejected_without_touching_target(self):
        target = self.path.with_name("target.json")
        target.write_text(self.example())
        self.path.symlink_to(target)
        with self.assertRaises(self.module.ConfigurationError): self.store.load()
        self.assertEqual(target.read_text(), self.example())

    def test_simultaneous_saves_have_one_winner_and_one_conflict(self):
        from concurrent.futures import ThreadPoolExecutor
        old = self.store.initialize()
        entry = old.entries["receiver-a"]
        def save(port):
            try:
                fresh = self.store.save({"receiver-a": replace(entry, config=replace(entry.config, port=port))},
                                        expected_revision=old.revision)
                return fresh.entries["receiver-a"].config.port
            except self.module.ConfigurationError as exc:
                return exc.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(save, (9002, 9003)))
        self.assertEqual(results.count("CONFIG_CONFLICT"), 1)
        self.assertIn(self.store.load().entries["receiver-a"].config.port, (9002, 9003))

    def test_busy_lock_and_unsafe_lock_do_not_overwrite_settings(self):
        import fcntl
        old = self.store.initialize()
        before = self.path.read_bytes()
        lock = self.path.with_name(self.path.name + ".lock")
        with lock.open("r+") as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            with self.assertRaises(self.module.ConfigurationError) as caught:
                self.store.save(old.entries, expected_revision=old.revision)
            self.assertEqual(caught.exception.code, "CONFIG_BUSY")
        self.assertEqual(self.path.read_bytes(), before)
        lock.chmod(0o666)
        with self.assertRaises(self.module.ConfigurationError):
            self.store.save(old.entries, expected_revision=old.revision)
        self.assertEqual(self.path.read_bytes(), before)

    def test_post_replace_fsync_failure_reports_uncertain_new_contents(self):
        old = self.store.initialize()
        entry = old.entries["receiver-a"]
        original = os.fsync
        calls = 0
        def fail_directory(fd):
            nonlocal calls
            calls += 1
            if calls == 2: raise OSError("test directory sync failed")
            return original(fd)
        with patch("os.fsync", side_effect=fail_directory):
            with self.assertRaises(self.module.ConfigurationError) as caught:
                self.store.save({"receiver-a": replace(entry, config=replace(entry.config, port=9002))},
                                expected_revision=old.revision)
        self.assertEqual(caught.exception.code, "CONFIG_DURABILITY_UNCERTAIN")
        self.assertEqual(self.store.load().entries["receiver-a"].config.port, 9002)

    def test_exact_file_boundary_and_duplicate_instances(self):
        document = self.example()
        self.write(document + " " * (1048576 - len(document)))
        self.assertEqual(len(self.store.load().entries), 1)
        with self.path.open("a") as stream: stream.write(" ")
        with self.assertRaises(self.module.ConfigurationError): self.store.load()
        record = json.loads(document)
        duplicate = dict(record["instances"][0])
        for name in ("receiver-a", "receiver-b"):
            duplicate["name"] = name
            self.write(json.dumps({"version": 1, "instances": record["instances"] + [duplicate]}))
            with self.assertRaises(self.module.ConfigurationError): self.store.load()
