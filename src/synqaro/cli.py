"""Application CLI; optional GUI dependencies are loaded only on launch."""

import argparse
import json
from pathlib import Path
import shlex
import sys


class _Usage(ValueError):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise _Usage(message)


def main(argv=None, *, runtime_root=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    structured = '--json' in arguments
    config_path = None

    def emit(event, *, result=None, error=None):
        if error is not None:
            actions = []
            for action in error.get('actions', []):
                if (config_path is not None and isinstance(action, list)
                        and action[:1] in (['synqaro'], ['simquaro']) and '--config' not in action):
                    action = [action[0], '--config', str(config_path), *action[1:]]
                actions.append(action)
            error = {**error, 'actions': actions}
        if structured:
            print(json.dumps({'version': 1, 'event': event, 'ok': error is None,
                'error' if error is not None else 'result': error if error is not None else result},
                ensure_ascii=True, allow_nan=False, separators=(',', ':')), flush=True)
        elif error is None:
            print(result['url'] + '\n' + result.get('message', ''), flush=True)
        if error is not None:
            print(f"{error['code']}: {error['message']}", file=sys.stderr, flush=True)
            for action in error['actions']:
                print('  ' + (shlex.join(action) if isinstance(action, list) else action), file=sys.stderr, flush=True)

    parser = _Parser(prog='synqaro', description='Control and inspect hardware and simulators.', allow_abbrev=False)
    parser.add_argument('--json', action='store_true', help='emit version-1 JSON records')
    parser.add_argument('--config', type=Path, help='select the shared inventory JSON file')
    commands = parser.add_subparsers(dest='command', required=True)
    gui = commands.add_parser('gui', help='open the hardware console (requires web extra)', allow_abbrev=False)
    gui.add_argument('--port', type=int, default=8765, help='local HTTP port (default: 8765)')
    gui.add_argument('--no-browser', action='store_true', help='print the URL without opening a browser')
    try:
        args = parser.parse_args(arguments)
        config_path = args.config
        if not 1 <= args.port <= 65535:
            raise _Usage('GUI port must be an integer from 1 to 65535')
        # Reuse the current inventory service without migrating user files.
        from simquaro.configuration import ConfigStore
        store = ConfigStore(config_path)
        if config_path is not None:
            config_path = store.path
        store.load()
        from synqaro.web.launch import launch
        return launch(store, port=args.port, no_browser=args.no_browser,
                      runtime_root=runtime_root, emit=emit)
    except SystemExit as error:
        return int(error.code)
    except KeyboardInterrupt:
        return 130
    except _Usage as error:
        emit('usage', error={'code': 'INVALID_USAGE', 'message': str(error),
                            'actions': [['synqaro', '--help']]})
        return 2
    except (ValueError, OSError) as error:
        emit('error', error={'code': getattr(error, 'code', 'RUNTIME_FAILURE'),
             'message': str(error), 'actions': [['simquaro', 'config', 'validate'], ['synqaro', '--help']]})
        return 1
