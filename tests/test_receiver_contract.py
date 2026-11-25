"""Contract-derived consistency checks; literal behavioral oracles stay separate."""

from copy import deepcopy
from decimal import Decimal
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest

from simquaro.models.fictitious_receiver.config import ReceiverConfig
from simquaro.models.fictitious_receiver.model import FictitiousReceiverSimulator
from synqaro_protocol.client import LocalFailure
from synqaro_protocol.codec import MAX_MESSAGE_BYTES, NumericToken, Request, Response
from synqaro_protocol.profiles.fictitious_receiver import ERROR_CATALOG, FICTITIOUS_RECEIVER_CONTRACT

ROOT = Path(__file__).resolve().parents[1]
AVAILABLE = all(importlib.util.find_spec(name) for name in ('yaml', 'jsonschema'))


@unittest.skipUnless(AVAILABLE, 'install development dependencies: bash install.sh --dev')
class ReceiverContractTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        from tools.validate_contracts import load_document, validate_document
        self.contract = load_document(ROOT / 'contracts/models/fictitious_receiver.yaml')
        self.assertEqual(validate_document(self.contract), [])
        self.assertEqual(self.contract['status'], 'approved')

    def test_generated_artifacts_are_current(self):
        result = subprocess.run([sys.executable, str(ROOT / 'tools/generate_receiver_contract.py'), '--check'],
                                capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_generation_rejects_draft_and_inconsistent_scan_definition(self):
        # Import the tool just as the command does, without a runtime YAML dependency.
        sys.path.insert(0, str(ROOT / 'tools'))
        try:
            from generate_receiver_contract import project
        finally:
            sys.path.pop(0)
        draft = deepcopy(self.contract)
        draft['status'] = 'draft'
        draft['approval'] = None
        with self.assertRaisesRegex(ValueError, 'approved'):
            project(draft)
        inconsistent = deepcopy(self.contract)
        inconsistent['procedures']['scan']['parameters']['start']['value']['maximum'] = 9
        with self.assertRaisesRegex(ValueError, 'must agree'):
            project(inconsistent)

    async def test_descriptor_and_capabilities_match_yaml(self):
        # Read the authoring source directly, not the generated runtime module.
        model = FictitiousReceiverSimulator(ReceiverConfig())
        self.addAsyncCleanup(model.close)
        result = await model.handle(Request('get', 1, {}, {'name': 'configuration'}), session_id='contract')
        response = result.response
        self.assertEqual(response.verb, 'ok')
        fields = self.contract['properties']['configuration']['value']['fields']
        self.assertEqual(set(response.fields), set(fields))
        for key, definition in fields.items():
            with self.subTest(field=key):
                value = response.fields[key]
                if 'enum' in definition:
                    if definition['type'] in ('integer', 'number'):
                        self.assertIsInstance(value, NumericToken)
                        self.assertIn(Decimal(value.text), [Decimal(str(x)) for x in definition['enum']])
                    else:
                        self.assertIn(value, definition['enum'])
                if definition['type'] == 'array':
                    self.assertCountEqual(value, definition['items']['enum'])
                if 'minLength' in definition:
                    self.assertIsInstance(value, str)
                    self.assertGreaterEqual(len(value), definition['minLength'])
        freq = self.contract['properties']['frequency']['value']
        procedures = self.contract['procedures']
        for field, expected in {
            'frequency_min': freq['minimum'], 'frequency_max': freq['maximum'],
            'frequency_resolution': freq['resolution'],
            'scan_max_dwell_ms': procedures['scan']['parameters']['dwell_ms']['value']['maximum'],
            'calibrate_timeout_ms': procedures['calibrate']['timing']['deadline_ms'],
            'scan_timeout_ms': procedures['scan']['timing']['deadline_ms'],
        }.items():
            self.assertEqual(Decimal(response.fields[field].text), Decimal(str(expected)))
        for access in ('readonly', 'readwrite'):
            self.assertCountEqual(response.fields[access + '_properties'],
                                  [n for n, p in self.contract['properties'].items() if p['access'] == access])
        self.assertCountEqual(response.fields['supported_procedures'], procedures)
        self.assertEqual(response.fields['frequency_unit'], freq['unit'])
        self.assertEqual(int(response.fields['max_message_bytes'].text), MAX_MESSAGE_BYTES)
        self.assertEqual(FICTITIOUS_RECEIVER_CONTRACT.limits.max_pending,
                         int(response.fields['max_pending_requests'].text))
        self.assertEqual(FICTITIOUS_RECEIVER_CONTRACT.limits.incomplete_timeout * 1000,
                         int(response.fields['incomplete_message_timeout_ms'].text))
        self.assertFalse(set(self.contract['errors']) - set(ERROR_CATALOG))
        FICTITIOUS_RECEIVER_CONTRACT.validate_descriptor(response, model.config.hardware_id)
        # Every required descriptor field must be checked before writes, not only a subset.
        for name in fields:
            with self.subTest(missing=name):
                incomplete = dict(response.fields)
                del incomplete[name]
                with self.assertRaises(LocalFailure):
                    FICTITIOUS_RECEIVER_CONTRACT.validate_descriptor(
                        Response('ok', 1, incomplete), model.config.hardware_id)
        # An illustrative simulator identity remains legal, not a firmware certificate.
        self.assertEqual(self.contract['hardware']['firmware_versions'], [])

    def test_scenario_traceability_has_exact_contract_scope_and_existing_test_ids(self):
        # Traceability is maintained deliberately; no claim that prose is executable.
        trace = json.loads((ROOT / 'tests/receiver_contract_traceability.json').read_text())
        self.assertEqual(trace['revision'], self.contract['revision'])
        self.assertEqual(set(trace['scenarios']), set(self.contract['scenarios']))
        import ast
        covered = set()
        for scenario, entry in trace['scenarios'].items():
            self.assertEqual(set(entry['requirements']), set(self.contract['scenarios'][scenario]['requirements']))
            covered.update(entry['requirements'])
            self.assertTrue(entry['tests'])
            for test_id in entry['tests']:
                path, class_name, method = test_id.split('::')
                with self.subTest(scenario=scenario, test=test_id):
                    tree = ast.parse((ROOT / path).read_text())
                    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name)
                    self.assertTrue(any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == method
                                        for node in cls.body))
        self.assertEqual(covered, set(self.contract['requirements']))
