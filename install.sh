#!/usr/bin/env bash
# Install an independent, user-local copy; never install into system Python.
set -euo pipefail
umask 077

fail() { printf 'Error: %s\n' "$*" >&2; exit 1; }
usage() {
    printf '%s\n' 'Usage: bash install.sh [--prefix DIR] [--python PATH] [--help]' \
        'Install the application and browser GUI for the current user.' \
        '  --prefix DIR   Application directory (default: XDG_DATA_HOME/synqaro' \
        '                 or ~/.local/share/synqaro).' \
        '  --python PATH  Use an installed Python 3.12+ with venv support.'
}

prefix_arg=''
python_arg=''
while (($#)); do
    case "$1" in
        --prefix|--python)
            (($# >= 2)) && [[ -n "$2" && "$2" != --* ]] || fail "$1 requires a value; see --help."
            if [[ "$1" == --prefix ]]; then prefix_arg=$2; else python_arg=$2; fi
            shift 2 ;;
        --help|-h) usage; exit 0 ;;
        *) fail "Unknown option: $1; see --help." ;;
    esac
done

[[ $(uname -s) == Linux ]] || fail 'This installer currently supports Linux only.'
for tool in realpath flock mktemp cp readlink; do
    command -v "$tool" >/dev/null || fail "Missing $tool; install your distribution's core utilities and retry."
done
source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
[[ -f "$source_dir/pyproject.toml" && -d "$source_dir/src/simquaro" ]] ||
    fail 'Extract the complete Synqaro download and run its install.sh again.'
user_home=$(realpath -m -- "${HOME:?HOME is not set}")
data_home=${XDG_DATA_HOME:-"$user_home/.local/share"}
[[ "$data_home" == /* ]] || data_home="$user_home/.local/share"
config_home=${XDG_CONFIG_HOME:-"$user_home/.config"}
[[ "$config_home" == /* ]] || config_home="$user_home/.config"
config_dir="$(realpath -m -- "$config_home")/simquaro"
launcher="$(realpath -m -- "$user_home/.local/bin")/simquaro"
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
launcher_target="$prefix/current/bin/simquaro"
if [[ -e "$launcher" || -L "$launcher" ]]; then
    [[ -L "$launcher" && $(readlink -- "$launcher") == "$launcher_target" ]] ||
        fail "Another launcher already exists at $launcher; keep it and resolve the name conflict before retrying."
fi
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
"$environment/bin/python" -I -c 'import simquaro, synqaro_protocol, fastapi, uvicorn'
env -u PYTHONHOME -u PYTHONPATH "$environment/bin/simquaro" --help >/dev/null
rm -rf --one-file-system -- "$environment/source"

# The environment keeps its original path (venv entry points contain absolute
# paths). Publish only after validation, without deleting environments that a
# previously launched application may still be using.
next_link="$environment/current-link"
ln -s -- "$environment" "$next_link"
mv -Tf -- "$next_link" "$prefix/current"
published=true
if [[ ! -L "$launcher" ]]; then ln -s -- "$launcher_target" "$launcher"; fi
printf 'Installation completed.\nLaunch the GUI: %q gui\n' "$launcher"
case ":${PATH:-}:" in
    *":$(dirname -- "$launcher"):"*) ;;
    *) printf '%s\n' 'The command directory is not on PATH. Use the full launch command shown above.' ;;
esac
