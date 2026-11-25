#!/usr/bin/env bash
# Install a user-local application or prepare a checkout for development.
set -euo pipefail
umask 077

fail() { printf 'Error: %s\n' "$*" >&2; exit 1; }
usage() {
    printf '%s\n' 'Usage: bash install.sh [--prefix DIR | --dev] [--python PATH] [--help]' \
        'Install the application and browser GUI for the current user.' \
        '  --dev          Install development/test dependencies in the checkout .venv;' \
        '                 do not install the application or create launchers.' \
        '  --prefix DIR   Application directory (default: XDG_DATA_HOME/synqaro' \
        '                 or ~/.local/share/synqaro).' \
        '  --python PATH  Use an installed Python 3.12+ with venv support.'
}

prefix_arg=''
python_arg=''
dev=false
while (($#)); do
    case "$1" in
        --prefix|--python)
            (($# >= 2)) && [[ -n "$2" && "$2" != --* ]] || fail "$1 requires a value; see --help."
            if [[ "$1" == --prefix ]]; then prefix_arg=$2; else python_arg=$2; fi
            shift 2 ;;
        --dev) dev=true; shift ;;
        --help|-h) usage; exit 0 ;;
        *) fail "Unknown option: $1; see --help." ;;
    esac
done

[[ $(uname -s) == Linux ]] || fail 'This installer currently supports Linux only.'
for tool in realpath flock mktemp cp readlink; do
    command -v "$tool" >/dev/null || fail "Missing $tool; install your distribution's core utilities and retry."
done
source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
[[ -f "$source_dir/pyproject.toml" && -d "$source_dir/src/simquaro" && -d "$source_dir/src/synqaro" ]] ||
    fail 'Extract the complete Synqaro download and run its install.sh again.'
select_python() {
    # Detect an existing supported interpreter; never replace system Python.
    python_command=''
    if [[ -n "$python_arg" ]]; then
        python_command=$(command -v -- "$python_arg") || fail 'Python executable not found; retry with --python /path/to/python3.12-or-newer.'
    else
        for candidate in python3 python3.14 python3.13 python3.12; do
            if command -v "$candidate" >/dev/null && "$candidate" -I -c 'import sys; sys.exit(sys.version_info < (3, 12))' 2>/dev/null; then
                python_command=$(command -v "$candidate")
                break
            fi
        done
    fi
    [[ -n "$python_command" ]] || fail 'Python 3.12+ is required. Install a supported Python, then retry, or select it with --python /path/to/python.'
    "$python_command" -I -c 'import sys; sys.exit(sys.version_info < (3, 12))' ||
        fail 'Python 3.12+ is required; select it with --python /path/to/python.'
    "$python_command" -I -c 'import venv, ensurepip, os; assert hasattr(os, "pidfd_open")' 2>/dev/null ||
        fail 'Python needs venv/ensurepip and Linux pidfd support. On Mint 22 / Ubuntu 24.04 with default Python, install python3-venv using the system package manager, then retry.'
}

if [[ "$dev" == true ]]; then
    [[ -z "$prefix_arg" ]] || fail '--dev uses the checkout .venv and cannot be combined with --prefix.'
    select_python
    environment="$source_dir/.venv"
    [[ ! -L "$environment" ]] || fail 'The development environment is a symbolic link; choose a real .venv directory.'
    if [[ -e "$environment" ]]; then
        [[ -d "$environment" && -O "$environment" && -f "$environment/pyvenv.cfg" && -x "$environment/bin/python" ]] ||
            fail 'Existing .venv is not a usable virtual environment; leave it untouched and inspect it before retrying.'
    else
        printf '%s\n' 'Preparing the checkout development environment...'
        env -u PYTHONHOME -u PYTHONPATH "$python_command" -I -m venv "$environment"
    fi
    # Validate the destination, including a reused environment, before pip runs.
    env -u PYTHONHOME -u PYTHONPATH "$environment/bin/python" -I - "$environment" "$python_command" "$python_arg" <<'PYTHON'
import os
from pathlib import Path
import subprocess
import sys

expected, interpreter, explicit = sys.argv[1:]
if (sys.version_info < (3, 12) or sys.prefix == sys.base_prefix
        or Path(sys.prefix).resolve() != Path(expected).resolve()):
    raise SystemExit('Error: .venv must be a local Python 3.12+ virtual environment.')
settings = dict(line.split('=', 1) for line in (Path(expected) / 'pyvenv.cfg').read_text().splitlines() if '=' in line)
if any(key.strip().lower() == 'include-system-site-packages' and value.strip().lower() == 'true'
       for key, value in settings.items()):
    raise SystemExit('Error: .venv must not include system site packages.')
if explicit:
    base = subprocess.check_output([interpreter, '-I', '-c',
                                    'import sys; print(sys._base_executable)'], text=True).strip()
    if not os.path.samefile(sys._base_executable, base):
        raise SystemExit('Error: existing .venv uses a different interpreter; select its Python or create a new environment.')
PYTHON
    printf '%s\n' 'Installing development and test dependencies (including GUI test prerequisites)...'
    # Keep dependency declarations in pyproject.toml. Install the requirements,
    # not the project itself; pytest reads the checkout directly.
    env -u PYTHONHOME -u PYTHONPATH -u PIP_TARGET -u PIP_PREFIX -u PIP_ROOT -u PIP_PYTHON \
        -u PIP_USER PIP_CONFIG_FILE=/dev/null "$environment/bin/python" -I - "$source_dir/pyproject.toml" <<'PYTHON'
from pathlib import Path
import subprocess
import sys
import tomllib

with Path(sys.argv[1]).open('rb') as stream:
    project = tomllib.load(stream)['project']
extras = project['optional-dependencies']
requirements = project['dependencies'] + extras['web'] + extras['dev']
subprocess.run([sys.executable, '-I', '-m', 'pip', '--disable-pip-version-check',
                'install', *requirements], check=True)
PYTHON
    printf 'Development dependencies installed.\nRun tests from the repository root:\n  source .venv/bin/activate\n  pytest\n  # Web tests only: pytest tests/web\n'
    exit 0
fi

user_home=$(realpath -m -- "${HOME:?HOME is not set}")
data_home=${XDG_DATA_HOME:-"$user_home/.local/share"}
[[ "$data_home" == /* ]] || data_home="$user_home/.local/share"
config_home=${XDG_CONFIG_HOME:-"$user_home/.config"}
[[ "$config_home" == /* ]] || config_home="$user_home/.config"
config_dir="$(realpath -m -- "$config_home")/simquaro"
launcher="$(realpath -m -- "$user_home/.local/bin")/simquaro"
gui_launcher="$(dirname -- "$launcher")/synqaro"
prefix_arg=${prefix_arg:-"$data_home/synqaro"}
[[ "$prefix_arg$config_dir$launcher" != *$'\n'* ]] || fail 'Paths must not contain newlines.'
prefix_lexical=$(realpath -ms -- "$prefix_arg")
[[ ! -L "$prefix_lexical" ]] || fail 'The installation directory is a symbolic link; choose a separate directory with --prefix.'
prefix=$(realpath -m -- "$prefix_lexical")
for protected in "$user_home" "$source_dir" "$(dirname -- "$launcher")" "$config_dir"; do
    [[ "$protected" != "$prefix" && "$protected" != "$prefix/"* && "$prefix" != / ]] ||
        fail 'Unsafe installation directory; choose a dedicated application directory with --prefix.'
done
[[ "$prefix" != "$source_dir/"* ]] || fail 'Choose an installation directory outside the downloaded source with --prefix.'

# Refuse to overwrite another program, even if it happens to use our name.
for candidate_launcher in "$launcher" "$gui_launcher"; do
    launcher_target="$prefix/current/bin/${candidate_launcher##*/}"
    if [[ -e "$candidate_launcher" || -L "$candidate_launcher" ]]; then
        [[ -L "$candidate_launcher" && $(readlink -- "$candidate_launcher") == "$launcher_target" ]] ||
            fail "Another launcher already exists at $candidate_launcher; keep it and resolve the name conflict before retrying."
    fi
done
# Keep the v1 marker and recorded simulator launcher valid on upgrades.
# The companion Synqaro launcher always uses that same directory and prefix.
marker="$prefix/.synqaro-installation"
validate_marker() {
    [[ -f "$marker" && ! -L "$marker" && -O "$marker" ]] || fail 'Unsafe installation marker; choose a different --prefix.'
    mapfile -t metadata < "$marker"
    [[ ${#metadata[@]} == 4 && ${metadata[0]} == 'synqaro-install-v1' &&
       ${metadata[1]} == "$prefix" && ${metadata[2]} == "$launcher" &&
       ${metadata[3]} == "$config_dir" ]] ||
        fail 'This directory belongs to a different installation or configuration location; use its original settings or another --prefix.'
}
if [[ -e "$prefix" ]]; then
    [[ -d "$prefix" && -O "$prefix" ]] || fail 'The installation directory must be owned by your user.'
    if [[ -e "$marker" || -L "$marker" ]]; then
        validate_marker
    else
        [[ -z $(ls -A -- "$prefix") ]] || fail 'The directory is not a managed Synqaro installation; choose a different --prefix.'
    fi
fi
if [[ -e "$prefix/current" || -L "$prefix/current" ]]; then
    [[ -L "$prefix/current" && $(readlink -- "$prefix/current") == "$prefix/environment."* ]] ||
        fail 'Unexpected current-environment path; leave it untouched and choose another --prefix.'
fi

select_python

mkdir -p -- "$(dirname -- "$prefix")" "$(dirname -- "$launcher")"
mkdir -p -- "$prefix"
if [[ ! -e "$marker" && ! -L "$marker" ]]; then
    # Publish a complete marker before creating anything else in the prefix.
    # The temporary file is a sibling, so a crash leaves an empty, retryable
    # prefix, never a nonempty directory with a truncated/missing marker.
    pending_marker=$(mktemp "$prefix.marker.XXXXXXXX")
    printf '%s\n' 'synqaro-install-v1' "$prefix" "$launcher" "$config_dir" > "$pending_marker"
    ln -- "$pending_marker" "$marker" 2>/dev/null || true
    rm -- "$pending_marker"
fi
validate_marker
[[ ! -L "$prefix/.maintenance.lock" ]] || fail 'Unsafe installation lock; choose another --prefix.'
if [[ -e "$prefix/.maintenance.lock" ]]; then
    [[ -f "$prefix/.maintenance.lock" && -O "$prefix/.maintenance.lock" &&
       $(stat -c %h -- "$prefix/.maintenance.lock") == 1 ]] || fail 'Unsafe installation lock; choose another --prefix.'
fi
exec 9>>"$prefix/.maintenance.lock"
flock -n 9 || fail 'Another installation or removal is in progress; wait for it to finish and retry.'

environment=''
published=false
cleanup() {
    result=$?
    if ((result != 0)); then
        if [[ "$published" == false && -n "$environment" &&
              "$environment" == "$prefix/environment."* && ! -L "$environment" ]]; then
            rm -rf --one-file-system -- "$environment"
        fi
        printf '%s\n' 'Installation did not complete. Read the error above, correct it, and rerun the same command. Existing user configuration was not changed.' >&2
    fi
}
trap cleanup EXIT

environment=$(mktemp -d "$prefix/environment.XXXXXXXX")
printf '%s\n' 'Preparing an isolated Python environment...'
env -u PYTHONHOME -u PYTHONPATH "$python_command" -I -m venv "$environment"
# Build from a private snapshot: neither pip nor the installed package depends
# on the user's extracted download or modifies that source tree.
mkdir -- "$environment/source"
cp -- "$source_dir/pyproject.toml" "$environment/source/"
cp -R -- "$source_dir/src" "$environment/source/src"
printf '%s\n' 'Installing the application and GUI dependencies (internet access may be required)...'
# User/global pip configuration must not redirect files outside this venv.
# Keep network/index environment settings, but discard destination overrides.
env -u PYTHONHOME -u PYTHONPATH -u PIP_TARGET -u PIP_PREFIX -u PIP_ROOT -u PIP_PYTHON \
    -u PIP_USER PIP_CONFIG_FILE=/dev/null "$environment/bin/python" -I -m pip \
    --disable-pip-version-check install "$environment/source[web]"
"$environment/bin/python" -I -c 'import synqaro.web.app, simquaro, synqaro_protocol, fastapi, uvicorn'
env -u PYTHONHOME -u PYTHONPATH "$environment/bin/simquaro" --help >/dev/null
env -u PYTHONHOME -u PYTHONPATH "$environment/bin/synqaro" gui --help >/dev/null
rm -rf --one-file-system -- "$environment/source"

# The environment keeps its original path (venv entry points contain absolute
# paths). Publish only after validation, without deleting environments that a
# previously launched application may still be using.
next_link="$environment/current-link"
ln -s -- "$environment" "$next_link"
mv -Tf -- "$next_link" "$prefix/current"
published=true
for candidate_launcher in "$launcher" "$gui_launcher"; do
    launcher_target="$prefix/current/bin/${candidate_launcher##*/}"
    if [[ ! -L "$candidate_launcher" ]]; then ln -s -- "$launcher_target" "$candidate_launcher"; fi
done
printf 'Installation completed.\nLaunch the GUI: %q gui\n' "$gui_launcher"
case ":${PATH:-}:" in
    *":$(dirname -- "$launcher"):"*) ;;
    *) printf '%s\n' 'The command directory is not on PATH. Use the full launch command shown above.' ;;
esac
