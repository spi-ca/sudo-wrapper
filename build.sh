#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"

zig_compile() {
    if [ -n "${ZIG:-}" ]; then
        "$ZIG" "$@"
    elif command -v zig >/dev/null 2>&1; then
        zig "$@"
    else
        mise exec -- zig "$@"
    fi
}

build_one() {
    mkdir -p -- "$(dirname -- "$2")"
    zig_compile build-exe "$1" \
        -target x86_64-linux-none -O small -fllvm -flld \
        -fstrip -fno-stack-check -fno-stack-protector -fno-unwind-tables \
        -static -fPIE --build-id=none -T link.ld \
        -femit-bin="$2"
    # The kernel uses program headers, not section headers. Keep ELF/program
    # headers intact and remove only unneeded section metadata.
    "${OBJCOPY:-objcopy}" --strip-section-headers "$2"
    chmod 0755 -- "$2"
}

# Preserve the optional source/output interface for non-privileged fixtures.
if [ "$#" -gt 0 ]; then
    if [ "$#" -gt 2 ]; then
        printf '%s\n' 'usage: build.sh [source.zig [output]]' >&2
        exit 2
    fi
    build_one "$1" "${2:-zig-out/bin/sudo}"
    exit 0
fi

alias=zig-out/bin/sudoedit
# Do not replace an unrelated file or a different symlink.
if [ -L "$alias" ] && [ "$(readlink -- "$alias")" = sudo ]; then
    :
elif [ -e "$alias" ] || [ -L "$alias" ]; then
    printf '%s\n' 'refusing to replace existing zig-out/bin/sudoedit' >&2
    exit 1
fi

build_one src/main.zig zig-out/bin/sudo
# A build-time literal substitution, never runtime name/path construction.
# Both executables come from the same source; argv[0] is forwarded unchanged.
visudo_source=$(mktemp "${TMPDIR:-/tmp}/sudo-wrapper-visudo.XXXXXX.zig")
trap 'rm -f -- "$visudo_source"' EXIT
trap 'exit 1' HUP INT TERM
sed 's@/usr/bin/sudo-rs@/usr/bin/visudo-rs@g' src/main.zig > "$visudo_source"
build_one "$visudo_source" zig-out/bin/visudo
if [ ! -L "$alias" ]; then
    ln -s sudo "$alias"
fi
