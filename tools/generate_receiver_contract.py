"""Generate the receiver-specific runtime definitions from the approved YAML.

Run from any directory; --check detects stale generated files without writing.
The common protocol and behavioral algorithms are intentionally not generated.
"""

import argparse
import hashlib
import json
from pprint import pformat

from validate_contracts import ROOT, load_document, validate_document

SOURCE = ROOT / 'contracts/models/fictitious_receiver.yaml'
PYTHON = ROOT / 'src/synqaro_protocol/profiles/_receiver_contract_data.py'
JAVASCRIPT = ROOT / 'src/synqaro/web/static/receiver-contract.js'
REFERENCE = ROOT / 'docs/fictitious_receiver_reference.md'


def project(document):
    errors = validate_document(document)
    if errors:
        raise ValueError('\n'.join(errors))
    if (document['status'] != 'approved' or document['schema_version'] != 1
            or document['hardware']['model'] != 'fictitious_receiver'
            or document['protocol']['version'] != '1'):
        raise ValueError('Expected an approved schema-v1, protocol-v1 receiver contract')
    properties = document['properties']
    procedures = document['procedures']
    if set(properties) != {'configuration', 'frequency'} or set(procedures) != {'calibrate', 'scan'}:
        raise ValueError('Review the receiver-specific behavioral adapter for changed operations')
    frequency = properties['frequency']['value']
    scan = procedures['scan']['parameters']
    if set(scan) != {'start', 'stop', 'unit', 'dwell_ms'} or procedures['calibrate']['parameters']:
        raise ValueError('Review the receiver-specific procedure adapter for changed parameters')
    for name in ('start', 'stop'):
        if any(scan[name]['value'][key] != frequency[key]
               for key in ('type', 'unit', 'minimum', 'maximum', 'resolution', 'representation')):
            raise ValueError(f'Scan {name} must agree with frequency')
    fields = properties['configuration']['value']['fields']
    descriptor = {}
    for name, definition in fields.items():
        if name in ('hardware_id', 'firmware_version', 'firmware_build'):
            continue
        if 'enum' in definition:
            if len(definition['enum']) != 1:
                raise ValueError(f'Expected one fixed descriptor value: {name}')
            descriptor[name] = definition['enum'][0]
        elif definition['type'] == 'array':
            descriptor[name] = definition['items']['enum']
            if len(descriptor[name]) != definition['minItems'] or len(descriptor[name]) != definition['maxItems']:
                raise ValueError(f'Expected exact capability set: {name}')
    descriptor.update(frequency_min=frequency['minimum'], frequency_max=frequency['maximum'],
                      frequency_resolution=frequency['resolution'],
                      calibrate_timeout_ms=procedures['calibrate']['timing']['deadline_ms'],
                      scan_timeout_ms=procedures['scan']['timing']['deadline_ms'],
                      scan_max_dwell_ms=scan['dwell_ms']['value']['maximum'])
    if set(fields) != set(descriptor) | {'hardware_id', 'firmware_version', 'firmware_build'}:
        raise ValueError('Review unmapped descriptor fields')
    for access in ('readonly', 'readwrite'):
        if set(descriptor[access + '_properties']) != {n for n, p in properties.items() if p['access'] == access}:
            raise ValueError('Descriptor and property access disagree')
    if (set(descriptor['supported_procedures']) != set(procedures)
            or descriptor['frequency_unit'] != frequency['unit']
            or scan['unit']['value']['enum'] != [frequency['unit']]
            or descriptor['protocol_version'] != int(document['protocol']['version'])
            or descriptor['hardware_model'] != document['hardware']['model']):
        raise ValueError('Descriptor disagrees with model definitions')
    if (frequency['type'] != 'number' or frequency['minimum'] <= 0
            or frequency['resolution'] <= 0 or descriptor['frequency_rounding'] != 'nearest_ties_up'
            or descriptor['scan_points'] < 2 or scan['dwell_ms']['value']['type'] != 'integer'
            or scan['dwell_ms']['value']['minimum'] < 1):
        raise ValueError('Review the supported exact-decimal receiver algorithms')
    # Export only the structured definitions needed at runtime, not the prose
    # requirements/scenarios or a second implementation of their semantics.
    projected_properties = {name: {'access': prop['access'],
                                    'value': {k: v for k, v in prop['value'].items() if k != 'fields'}}
                            for name, prop in properties.items()}
    projected_procedures = {name: {'parameters': proc['parameters'], 'states': list(proc['states']),
                                    'cancellation': {'supported': proc['cancellation']['supported']},
                                    'timing': {'deadline_ms': proc['timing']['deadline_ms']}}
                            for name, proc in procedures.items()}
    return {'revision': document['revision'], 'model': document['hardware']['model'],
            'firmware_versions': document['hardware']['firmware_versions'], 'descriptor': descriptor,
            'properties': projected_properties, 'procedures': projected_procedures}


def outputs(document, digest):
    data = project(document)
    header = 'Generated by tools/generate_receiver_contract.py from contracts/models/fictitious_receiver.yaml. Do not edit.'
    lines = [f'<!-- {header} -->', '# Fictitious receiver: structured reference', '',
             f'Approved revision `{data["revision"]}`; source SHA-256 `{digest}`.', '',
             'See the [approved contract](../contracts/models/fictitious_receiver.yaml) for behavior,',
             'requirements, verification scenarios and scope. This generated reference is not a firmware',
             'certification or an independent conformance test.', '', '## Fixed descriptor fields', '',
             '| Field | Value |', '| --- | --- |']
    for key, value in data['descriptor'].items():
        lines.append(f'| `{key}` | `{json.dumps(value, ensure_ascii=True)}` |')
    lines.extend(['', '## Properties', '', '| Name | Access | Type | Unit |', '| --- | --- | --- | --- |'])
    for name, prop in data['properties'].items():
        value = prop['value']
        lines.append(f'| `{name}` | {prop["access"]} | {value["type"]} | {value["unit"] or "—"} |')
    lines.extend(['', '## Procedure parameters', '', '| Procedure | Parameter | Type | Unit | Bounds / values |',
                  '| --- | --- | --- | --- | --- |'])
    for name, proc in data['procedures'].items():
        if not proc['parameters']:
            lines.append(f'| `{name}` | None | — | — | — |')
        for parameter, entry in proc['parameters'].items():
            value = entry['value']
            limits = (f'{value["minimum"]}–{value["maximum"]}' if 'minimum' in value else
                      ', '.join(map(str, value.get('enum', []))))
            lines.append(f'| `{name}` | `{parameter}` | {value["type"]} | {value["unit"] or "—"} | {limits} |')
    return {PYTHON: f'"""{header}"""\n\nSOURCE_SHA256 = {digest!r}\nDATA = {pformat(data, width=110, sort_dicts=False)}\n',
            JAVASCRIPT: f'// {header}\n// Source SHA-256: {digest}\nconst RECEIVER_SPEC = {json.dumps(data, indent=2, ensure_ascii=True)};\n',
            REFERENCE: '\n'.join(lines) + '\n'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args(argv)
    expected = outputs(load_document(SOURCE), hashlib.sha256(SOURCE.read_bytes()).hexdigest())
    stale = []
    for path, content in expected.items():
        if args.check:
            if not path.is_file() or path.read_text(encoding='utf-8') != content:
                stale.append(path.relative_to(ROOT))
        else:
            path.write_text(content, encoding='utf-8')
    if stale:
        print('Stale generated receiver artifacts: ' + ', '.join(map(str, stale)))
    return int(bool(stale))


if __name__ == '__main__':
    raise SystemExit(main())
