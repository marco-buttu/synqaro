"""Offline authoring validation. Does not approve contracts or contact hardware."""

import argparse
import json
import math
from pathlib import Path
import sys

try:
    import yaml
    from jsonschema import Draft202012Validator, FormatChecker
except ImportError:
    raise SystemExit('Install contract tools with: python -m pip install -e ".[contracts]"')

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / 'contracts/schema-v1.json').read_text())
Draft202012Validator.check_schema(SCHEMA)
VALIDATOR = Draft202012Validator(SCHEMA, format_checker=FormatChecker())


class ContractLoader(yaml.SafeLoader):
    """Reject ambiguous mapping keys and aliases rather than normalizing them."""

    def compose_node(self, parent, index):
        if self.check_event(yaml.AliasEvent):
            raise ValueError('YAML aliases are not supported; write explicit definitions')
        if getattr(self.peek_event(), 'tag', None) is not None:
            raise ValueError('Explicit YAML tags are not supported; use plain values or quoted strings')
        return super().compose_node(parent, index)

    def construct_mapping(self, node, deep=False):
        result = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if type(key) is not str:
                raise ValueError(f'line {key_node.start_mark.line + 1}: mapping keys must be strings')
            if key in result:
                raise ValueError(f'line {key_node.start_mark.line + 1}: duplicate key {key!r}')
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def _json_data(value, path='$', depth=0):
    if depth > 64:
        raise ValueError(f'{path}: maximum nesting depth is 64')
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise ValueError(f'{path}: keys must be strings')
            _json_data(item, f'{path}.{key}', depth + 1)
    elif type(value) is list:
        for index, item in enumerate(value):
            _json_data(item, f'{path}[{index}]', depth + 1)
    elif type(value) is float and not math.isfinite(value):
        raise ValueError(f'{path}: numbers must be finite')
    elif value is not None and type(value) not in (str, int, float, bool):
        raise ValueError(f'{path}: unsupported YAML value; quote dates and version strings')


def _json_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'duplicate key {key!r}')
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError(f'Invalid JSON numeric constant: {value}')


def load_document(path):
    try:
        with Path(path).open('rb') as stream:
            raw = stream.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ValueError('Contract exceeds 1 MiB authoring limit')
        text = raw.decode('utf-8')
        if Path(path).suffix.lower() == '.json':
            result = json.loads(text, object_pairs_hook=_json_pairs, parse_constant=_invalid_constant)
        else:
            result = yaml.load(text, Loader=ContractLoader)
        _json_data(result)
        return result
    except (yaml.YAMLError, UnicodeError, RecursionError) as error:
        raise ValueError(f'Invalid document: {error}') from error


def _value_errors(value, path):
    errors = []
    kind = value['type']
    permitted = {'minimum', 'maximum', 'resolution', 'representation'} if kind in ('number', 'integer') else set()
    if kind == 'string': permitted |= {'minLength', 'maxLength'}
    if kind == 'array': permitted |= {'minItems', 'maxItems', 'items'}
    if kind == 'object': permitted |= {'fields'}
    for key in value.keys() - {'type', 'unit', 'description', 'enum'} - permitted:
        errors.append(f'{path}.{key}: not applicable to {kind}')
    for low, high in [('minimum', 'maximum'), ('minItems', 'maxItems'), ('minLength', 'maxLength')]:
        if low in value and high in value and value[low] > value[high]:
            errors.append(f'{path}: {low} must not exceed {high}')
    if kind == 'integer':
        for key in ('minimum', 'maximum', 'resolution'):
            if key in value and int(value[key]) != value[key]:
                errors.append(f'{path}.{key}: integer constraints must be integral')
    if kind == 'array':
        if 'items' not in value: errors.append(f'{path}: array requires items')
        else: errors.extend(_value_errors(value['items'], path + '.items'))
    if kind == 'object':
        if 'fields' not in value: errors.append(f'{path}: object requires fields')
        else:
            for name, field in value['fields'].items():
                errors.extend(_value_errors(field, f'{path}.fields.{name}'))
    if 'enum' in value:
        if kind in ('array', 'object'):
            errors.append(f'{path}: enum is only supported for scalar values')
        else:
            constraints = {key: value[key] for key in ('type', 'minimum', 'maximum', 'minLength', 'maxLength') if key in value}
            for item in value['enum']:
                if not Draft202012Validator(constraints).is_valid(item):
                    errors.append(f'{path}.enum: value {item!r} violates its type or constraints')
    return errors


def validate_document(document):
    """Return structural/consistency errors; an empty list is not approval."""
    try:
        _json_data(document)
    except ValueError as error:
        return [str(error)]
    def leaves(error):
        if error.context:
            for child in error.context:
                yield from leaves(child)
        else:
            yield error

    errors = [f"{'.'.join(map(str, error.absolute_path)) or '$'}: {error.message}"
              for parent in VALIDATOR.iter_errors(document) for error in leaves(parent)]
    if errors:
        return sorted(errors)

    def refs(values, section, path):
        for name in values:
            if name not in document[section]:
                errors.append(f'{path}: unknown reference {name!r} in {section}')

    for section in ('properties', 'procedures', 'scenarios', 'open_items'):
        for name, definition in document[section].items():
            refs(definition['requirements'], 'requirements', f'{section}.{name}.requirements')
            if 'errors' in definition:
                refs(definition['errors'], 'errors', f'{section}.{name}.errors')
    for name, requirement in document['requirements'].items():
        refs(requirement['sources'], 'sources', f'requirements.{name}.sources')
        refs(requirement['dependencies'], 'dependencies', f'requirements.{name}.dependencies')
    for name, prop in document['properties'].items():
        errors.extend(_value_errors(prop['value'], f'properties.{name}.value'))
    for name, procedure in document['procedures'].items():
        path = f'procedures.{name}'
        for parameter, definition in procedure['parameters'].items():
            errors.extend(_value_errors(definition['value'], f'{path}.parameters.{parameter}.value'))
        states, terminal = set(procedure['states']), set(procedure['terminal_states'])
        used = {procedure['initial_state']} | terminal | set(procedure['cancellation']['allowed_states'])
        for transition in procedure['transitions']:
            used |= {transition['from'], transition['to']}
            if transition['from'] in terminal:
                errors.append(f'{path}.transitions: terminal state cannot have an outgoing transition')
        if used - states: errors.append(f'{path}: undefined states {sorted(used - states)}')
        if set(procedure['outcomes']) != terminal:
            errors.append(f'{path}.outcomes: describe exactly the terminal_states')
        cancellation = procedure['cancellation']
        if bool(cancellation['allowed_states']) != cancellation['supported']:
            errors.append(f'{path}.cancellation: supported must agree with allowed_states')
        if terminal & set(cancellation['allowed_states']):
            errors.append(f'{path}.cancellation: cannot cancel a terminal state')
        reachable = {procedure['initial_state']}
        while True:
            expanded = reachable | {t['to'] for t in procedure['transitions'] if t['from'] in reachable}
            if expanded == reachable: break
            reachable = expanded
        if states - reachable: errors.append(f'{path}: unreachable states {sorted(states - reachable)}')
        if 'deadline_ms' in procedure['timing']:
            terminates = set(terminal)
            while True:
                expanded = terminates | {t['from'] for t in procedure['transitions'] if t['to'] in terminates}
                if expanded == terminates: break
                terminates = expanded
            if states - terminates:
                errors.append(f'{path}: finite deadline but no path to a terminal state from {sorted(states - terminates)}')
    approval = document['approval']
    if document['status'] == 'draft' and approval is not None:
        errors.append('approval: draft must use null; approval belongs to an approved revision')
    if document['status'] == 'approved':
        if approval is None:
            errors.append('approval: approved contract requires approval metadata')
        elif approval['revision'] != document['revision']:
            errors.append('approval.revision: must match contract revision')
        covered = {r for scenario in document['scenarios'].values() for r in scenario['requirements']}
        for name, requirement in document['requirements'].items():
            if requirement['status'] != 'confirmed': errors.append(f'requirements.{name}: still proposed')
            if name not in covered: errors.append(f'requirements.{name}: no scenario references this requirement')
            for dependency in requirement['dependencies']:
                entry = document['dependencies'].get(dependency)
                if entry and entry['status'] not in ('available', 'approved_pending_verification'):
                    errors.append(f'requirements.{name}: unapproved dependency {dependency}')
        for name, item in document['open_items'].items():
            if item['disposition'] == 'blocking': errors.append(f'open_items.{name}: blocking question in approved contract')
            elif item['requirements']: errors.append(f'open_items.{name}: excluded scope still references included requirements')
    return sorted(errors)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('paths', nargs='*', type=Path, help='YAML or JSON contract files')
    args = parser.parse_args(argv)
    paths = args.paths or sorted(path for folder in ('examples', 'models')
                                for path in (ROOT / 'contracts' / folder).rglob('*')
                                if path.suffix in ('.yaml', '.yml', '.json'))
    if not paths:
        print('No contracts found', file=sys.stderr)
        return 1
    failed = False
    for path in paths:
        try:
            errors = validate_document(load_document(path))
        except (OSError, ValueError) as error:
            errors = [str(error)]
        if errors:
            failed = True
            for error in errors: print(f'{path}: {error}', file=sys.stderr)
        else:
            print(f'{path}: valid structure/consistency; not approval or proof of hardware behavior')
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
