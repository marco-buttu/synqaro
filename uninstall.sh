#!/usr/bin/env bash
# Remove only a marked user-local installation and explicitly selected config.
set -euo pipefail
umask 077

fail() { printf 'Error: %s\n' "$*" >&2; exit 1; }
usage() {
    printf '%s\n' 'Usage: bash uninstall.sh [--prefix DIR] [--purge] [--yes] [--help]' \
        'Remove the application; preserve user configuration by default.' \
        '  --prefix DIR   Select the directory used during installation.' \
        '  --purge        Also remove managed default configuration files.' \
        '  --yes          Confirm configuration removal without prompting.'
}

prefix_arg=''
purge=false
yes=false
while (($#)); do
    case "$1" in
        --prefix)
            (($# >= 2)) && [[ -n "$2" && "$2" != --* ]] || fail '--prefix requires a directory; see --help.'
            prefix_arg=$2; shift 2 ;;
        --purge) purge=true; shift ;;
        --yes) yes=true; shift ;;
        --help|-h) usage; exit 0 ;;
        *) fail "Unknown option: $1; see --help." ;;
    esac
done

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
[[ ! -L "$prefix_lexical" ]] || fail 'The installation directory is a symbolic link; leave it untouched and select the original directory with --prefix.'
prefix=$(realpath -m -- "$prefix_lexical")
source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
for protected in "$user_home" "$source_dir" "$(dirname -- "$launcher")" "$config_dir"; do
    [[ "$protected" != "$prefix" && "$protected" != "$prefix/"* && "$prefix" != / ]] ||
        fail 'Unsafe installation directory; select the dedicated application directory with --prefix.'
done
marker="$prefix/.synqaro-installation"
managed=false
# A removal interrupted after deleting its final marker can leave only an
# empty directory. It is safe to finish with rmdir (never recursive deletion).
empty_prefix=false
if [[ -d "$prefix" && -O "$prefix" && -z $(ls -A -- "$prefix") ]]; then empty_prefix=true; fi
if [[ -e "$prefix" && "$empty_prefix" == false ]]; then
    [[ -d "$prefix" && -O "$prefix" && -f "$marker" && ! -L "$marker" && -O "$marker" ]] ||
        fail 'This is not a managed Synqaro installation; leave it untouched and check --prefix.'
    mapfile -t metadata < "$marker"
    [[ ${#metadata[@]} == 4 && ${metadata[0]} == 'synqaro-install-v1' &&
       ${metadata[1]} == "$prefix" && ${metadata[2]} == "$launcher" &&
       ${metadata[3]} == /*/simquaro ]] || fail 'Invalid installation marker; nothing was removed.'
    config_dir=${metadata[3]}
    managed=true
    [[ ! -L "$prefix/.maintenance.lock" ]] || fail 'Unsafe installation lock; nothing was removed.'
    if [[ -e "$prefix/.maintenance.lock" ]]; then
        [[ -f "$prefix/.maintenance.lock" && -O "$prefix/.maintenance.lock" &&
           $(stat -c %h -- "$prefix/.maintenance.lock") == 1 ]] || fail 'Unsafe installation lock; nothing was removed.'
    fi
    exec 9>>"$prefix/.maintenance.lock"
    flock -n 9 || fail 'Another installation or removal is in progress; wait for it to finish and retry.'
    # Do not delete code from underneath a running GUI, console, or simulator.
    for command_line in /proc/[0-9]*/cmdline; do
        executable=''
        if IFS= read -r -d '' executable < "$command_line" 2>/dev/null; then
            [[ "$executable" != "$prefix/"* ]] ||
                fail 'The application is still running. Close its GUI (Ctrl+C in its terminal), run simquaro stop all, close any consoles, and retry removal.'
        fi
    done
fi

if [[ "$purge" == true ]]; then
    [[ $(realpath -m -- "$config_dir") == "$config_dir" ]] ||
        fail 'The configuration path now resolves to a different directory; nothing was removed. Inspect its symbolic links before retrying.'
    [[ ! -L "$config_dir" ]] || fail 'The configuration directory is a symbolic link; nothing was removed. Inspect it before retrying.'
    [[ ! -e "$config_dir" || ( -d "$config_dir" && -O "$config_dir" ) ]] ||
        fail 'The configuration directory must belong to your user; nothing was removed.'
    printf 'Configuration files selected for removal:\n  %s\n  %s\n' \
        "$config_dir/instances.json" "$config_dir/instances.json.lock"
    if [[ "$yes" == false ]]; then
        [[ -t 0 ]] || fail 'Configuration removal needs confirmation. Use --purge --yes only if you intend to delete the listed configuration files.'
        read -r -p 'Remove the application and these configuration files? [y/N] ' answer || answer=''
        case "$answer" in
            y|Y|yes|YES) ;;
            *) printf '%s\n' 'Cancelled; nothing was removed.'; exit 0 ;;
        esac
    fi
    for file in "$config_dir/instances.json" "$config_dir/instances.json.lock"; do
        [[ ! -e "$file" || -f "$file" || -L "$file" ]] || fail "Not a configuration file: $file; nothing was removed."
    done
fi

launcher_target="$prefix/current/bin/simquaro"
if [[ -L "$launcher" && $(readlink -- "$launcher") == "$launcher_target" ]]; then
    rm -- "$launcher"
fi
if [[ -d "$prefix" ]]; then
    if [[ "$managed" == true ]]; then
        # Keep ownership evidence until all payload is gone. -xdev and the
        # default no-follow traversal also refuse to cross mounted subtrees.
        find "$prefix" -xdev -depth -mindepth 1 ! -samefile "$marker" \
            ! -samefile "$prefix/.maintenance.lock" -delete
        rm -- "$prefix/.maintenance.lock" "$marker"
    fi
    rmdir -- "$prefix"
    printf '%s\n' 'Application removed.'
else
    printf '%s\n' 'The application is already uninstalled.'
fi
if [[ "$purge" == true ]]; then
    rm -f -- "$config_dir/instances.json" "$config_dir/instances.json.lock"
    if [[ -d "$config_dir" ]]; then rmdir -- "$config_dir" 2>/dev/null || true; fi
    printf '%s\n' 'Managed configuration removed. Unrelated files and external configuration files were left untouched.'
else
    printf '%s\n' 'Configuration and user data were preserved.'
fi
