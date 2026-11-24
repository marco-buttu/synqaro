"""Contract authoring checks, independent of firmware and simulator behavior."""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
AVAILABLE = all(importlib.util.find_spec(name) for name in ('yaml', 'jsonschema'))


@unittest.skipUnless(AVAILABLE, 'install development extra: pip install -e ".[contracts]"')
class ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('contract_validator', ROOT / 'tools/validate_contracts.py')
        cls.validator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.validator)

    def setUp(self):
        self.example = self.validator.load_document(ROOT / 'contracts/examples/indicator.yaml')

    def assertInvalid(self, document, fragment):
        errors = self.validator.validate_document(document)
        self.assertTrue(errors)
        self.assertIn(fragment, '\n'.join(errors))

    def test_example_and_schema_are_valid(self):
        self.assertEqual(self.validator.validate_document(self.example), [])

    def test_required_sections_version_and_unknown_fields(self):
        for key in self.example:
            with self.subTest(missing=key):
                data = deepcopy(self.example)
                del data[key]
                self.assertInvalid(data, key)
        for key, value in [('schema_version', 2), ('typo', True), ('status', 'verified')]:
            with self.subTest(key=key):
                data = deepcopy(self.example)
                data[key] = value
                self.assertTrue(self.validator.validate_document(data))

    def test_wrong_types_and_empty_required_text(self):
        for value in [True, 1, '', '   ']:
            with self.subTest(value=value):
                data = deepcopy(self.example)
                data['hardware']['model'] = value
                self.assertInvalid(data, 'hardware.model')
        data = deepcopy(self.example)
        data['properties']['level']['access'] = 'writeonly'
        self.assertInvalid(data, 'access')

    def test_firmware_versions_may_be_empty_before_firmware_exists(self):
        for data in (deepcopy(self.example), self.approved()):
            with self.subTest(status=data['status']):
                data['hardware']['firmware_versions'] = []
                self.assertEqual(self.validator.validate_document(data), [])

    def test_firmware_versions_remain_explicit_unique_strings(self):
        for value in (None, '0.1.0', [1], [True], [''], ['   '], ['0.1.0', '0.1.0']):
            with self.subTest(value=value):
                data = deepcopy(self.example)
                data['hardware']['firmware_versions'] = value
                self.assertInvalid(data, 'hardware.firmware_versions')
        data = deepcopy(self.example)
        del data['hardware']['firmware_versions']
        self.assertInvalid(data, 'firmware_versions')
        data['hardware']['firmware_versions'] = ['0.1.0', '0.2.0']
        self.assertEqual(self.validator.validate_document(data), [])

    def test_reference_checks(self):
        cases = [
            ('properties', 'level', 'requirements', ['absent']),
            ('properties', 'level', 'errors', ['absent']),
            ('requirements', 'level_behavior', 'sources', ['absent']),
            ('requirements', 'level_behavior', 'dependencies', ['absent']),
            ('scenarios', 'set_level', 'requirements', ['absent']),
            ('open_items', 'future_scope', 'requirements', ['absent']),
        ]
        for section, name, key, value in cases:
            with self.subTest(section=section, key=key):
                data = deepcopy(self.example)
                data[section][name][key] = value
                self.assertInvalid(data, 'unknown reference')

    def test_numeric_and_collection_constraints(self):
        cases = [
            {'type': 'number', 'minimum': 5, 'maximum': 2},
            {'type': 'number', 'resolution': 0},
            {'type': 'integer', 'minimum': 0.5},
            {'type': 'string', 'minimum': 1},
            {'type': 'array', 'minItems': 3, 'maxItems': 2, 'items': {'type': 'boolean', 'unit': None, 'description': 'flag'}},
            {'type': 'array'},
            {'type': 'object'},
            {'type': 'boolean', 'enum': [0, 1]},
            {'type': 'integer', 'minimum': 1, 'enum': [0]},
        ]
        for changes in cases:
            with self.subTest(changes=changes):
                data = deepcopy(self.example)
                data['properties']['level']['value'] = {'unit': None, 'description': 'test', **changes}
                self.assertTrue(self.validator.validate_document(data))

    def test_procedure_state_integrity(self):
        for field, value in [('initial_state', 'missing'), ('terminal_states', ['missing']),
                             ('outcomes', {'missing': 'Done'}),
                             ('transitions', [{'from': 'running', 'to': 'missing', 'condition': 'Finish'}])]:
            with self.subTest(field=field):
                data = deepcopy(self.example)
                data['procedures']['self_check'][field] = value
                self.assertInvalid(data, 'procedures.self_check')
        data = deepcopy(self.example)
        data['procedures']['self_check']['cancellation']['allowed_states'] = ['running']
        self.assertInvalid(data, 'cancellation')

    def test_nested_values_and_parameter_rules(self):
        data = deepcopy(self.example)
        value = {'type': 'array', 'unit': None, 'description': 'flags', 'minItems': 1,
                 'items': {'type': 'boolean', 'unit': None, 'description': 'flag'}}
        data['properties']['level']['value'] = {'type': 'object', 'unit': None,
            'description': 'Structured sample', 'fields': {'flags': deepcopy(value)}}
        self.assertEqual(self.validator.validate_document(data), [])
        data['properties']['level']['value']['fields']['flags']['items']['minimum'] = 1
        self.assertInvalid(data, 'not applicable')
        data = deepcopy(self.example)
        data['procedures']['self_check']['parameters']['flags'] = {'required': False, 'value': value}
        self.assertInvalid(data, 'when_omitted')
        data['procedures']['self_check']['parameters']['flags']['when_omitted'] = 'Use the current flags.'
        self.assertEqual(self.validator.validate_document(data), [])

    def test_readonly_properties_do_not_declare_write_effects(self):
        data = deepcopy(self.example)
        data['properties']['level']['access'] = 'readonly'
        self.assertTrue(self.validator.validate_document(data))
        del data['properties']['level']['write_effect']
        self.assertEqual(self.validator.validate_document(data), [])

    def test_graph_and_cancellation_consistency(self):
        data = deepcopy(self.example)
        data['procedures']['self_check']['states']['unused'] = 'Unreachable state'
        self.assertInvalid(data, 'unreachable')
        data = deepcopy(self.example)
        data['procedures']['self_check']['transitions'].append(
            {'from': 'succeeded', 'to': 'running', 'condition': 'Restart'})
        self.assertInvalid(data, 'terminal state')
        data = deepcopy(self.example)
        data['procedures']['self_check']['cancellation'] = {
            'supported': True, 'allowed_states': ['succeeded'], 'semantics': 'Invalid cancellation'}
        self.assertInvalid(data, 'terminal state')

    def test_date_and_excluded_scope(self):
        data = self.approved()
        data['approval']['at'] = '2026-02-30'
        self.assertInvalid(data, 'approval.at')
        data = self.approved()
        data['open_items'] = deepcopy(self.example['open_items'])
        item = data['open_items']['future_scope']
        item['disposition'] = 'excluded'
        self.assertInvalid(data, 'exclusion_reason')
        item['exclusion_reason'] = 'Outside this revision.'
        self.assertEqual(self.validator.validate_document(data), [])
        item['requirements'] = ['level_behavior']
        self.assertInvalid(data, 'included requirements')

    def test_json_input_and_cli_io_errors(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'contract.json'
            path.write_text(json.dumps(self.example))
            self.assertEqual(self.validator.load_document(path), self.example)
            path.write_bytes(b'\xff')
            with self.assertRaises(ValueError):
                self.validator.load_document(path)
            path.write_bytes(b' ' * (1024 * 1024 + 1))
            with self.assertRaisesRegex(ValueError, '1 MiB'):
                self.validator.load_document(path)
            result = subprocess.run([sys.executable, str(ROOT / 'tools/validate_contracts.py'), str(path / 'missing')],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertNotIn('Traceback', result.stderr)

    def test_json_scientific_numbers_keep_numeric_type(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'contract.json'
            data = deepcopy(self.example)
            data['properties']['level']['value'] = {'type': 'number', 'unit': None,
                'description': 'Small numeric bound', 'minimum': 1e-7, 'maximum': 1e-6}
            path.write_text(json.dumps(data))
            loaded = self.validator.load_document(path)
            self.assertEqual(loaded['properties']['level']['value']['minimum'], 1e-7)
            self.assertEqual(self.validator.validate_document(loaded), [])
            data['hardware']['model'] = 1e-7
            path.write_text(json.dumps(data))
            self.assertInvalid(self.validator.load_document(path), 'hardware.model')
            for text in ['{"id": "one", "id": "two"}', '{"number": NaN}', '{"number": 1e999}']:
                path.write_text(text)
                with self.assertRaises(ValueError):
                    self.validator.load_document(path)

    def test_explicit_yaml_tags_do_not_crash_or_abort_batch(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'bad.yaml'
            for content in ['id: !!bool perhaps', 'x: !!float ""']:
                with self.subTest(content=content):
                    path.write_text(content)
                    result = subprocess.run([sys.executable, str(ROOT / 'tools/validate_contracts.py'),
                        str(path), str(ROOT / 'contracts/examples/indicator.yaml')], capture_output=True, text=True)
                    self.assertEqual(result.returncode, 1)
                    self.assertNotIn('Traceback', result.stderr)
                    self.assertIn('not approval', result.stdout)

    def test_finite_deadline_cannot_have_nonterminating_branch(self):
        data = deepcopy(self.example)
        procedure = data['procedures']['self_check']
        procedure['states']['stuck'] = 'No completion is possible'
        procedure['transitions'].append({'from': 'running', 'to': 'stuck', 'condition': 'Fault'})
        self.assertInvalid(data, 'no path to a terminal state')
        del procedure['timing']['deadline_ms']
        procedure['timing']['completion'] = 'May remain stuck indefinitely; requires manual intervention.'
        self.assertEqual(self.validator.validate_document(data), [])

    def approved(self):
        data = deepcopy(self.example)
        data['status'] = 'approved'
        data['open_items'] = {}
        for requirement in data['requirements'].values():
            requirement['status'] = 'confirmed'
        data['approval'] = {'by': 'Example reviewer', 'at': '2026-11-19', 'revision': data['revision'],
                            'evidence': {'document': 'example-review', 'revision': '1'}}
        return data

    def test_approval_is_consistent_but_not_authenticated(self):
        data = self.approved()
        self.assertEqual(self.validator.validate_document(data), [])
        data['approval']['revision'] = 'other'
        self.assertInvalid(data, 'revision')
        data = self.approved()
        data['approval'] = None
        self.assertInvalid(data, 'approval')
        data = self.approved()
        data['requirements']['level_behavior']['status'] = 'proposed'
        self.assertInvalid(data, 'proposed')
        data = self.approved()
        data['open_items'] = deepcopy(self.example['open_items'])
        self.assertInvalid(data, 'blocking')

    def test_dependency_approval_is_not_availability(self):
        data = self.approved()
        data['dependencies']['extension'] = {'description': 'Example extension',
            'proposal': {'document': 'example-proposal', 'revision': '1'}, 'status': 'awaiting_approval'}
        data['requirements']['level_behavior']['dependencies'] = ['extension']
        self.assertInvalid(data, 'unapproved dependency')
        data['dependencies']['extension']['status'] = 'approved_pending_verification'
        self.assertEqual(self.validator.validate_document(data), [])
        data['dependencies']['extension']['status'] = 'available'
        self.assertInvalid(data, 'evidence')

    def test_requirement_coverage(self):
        data = self.approved()
        data['requirements']['new_requirement'] = deepcopy(data['requirements']['level_behavior'])
        self.assertInvalid(data, 'no scenario')

    def test_parser_rejects_ambiguous_or_unsafe_documents(self):
        samples = ['id: one\nid: two\n', 'x: &a [*a]\n', 'x: .nan\n',
                   'x: !!python/object:Thing {}\n', 'true: value\n', 'x: [\n',
                   'x: 1\n---\nx: 2\n']
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / 'invalid.yaml'
            for content in samples:
                with self.subTest(content=content):
                    file.write_text(content)
                    with self.assertRaises(ValueError):
                        self.validator.load_document(file)

    def test_cli_and_all_repository_contracts(self):
        result = subprocess.run([sys.executable, str(ROOT / 'tools/validate_contracts.py')],
                                capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn('not approval', result.stdout)
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / 'bad.json'
            file.write_text(json.dumps({'schema_version': 99}))
            result = subprocess.run([sys.executable, str(ROOT / 'tools/validate_contracts.py'), str(file)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn('schema_version', result.stderr)
            self.assertNotIn('Traceback', result.stderr)
