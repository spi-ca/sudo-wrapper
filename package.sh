#!/bin/sh
# Package already-verified binaries; never installs or elevates privileges.
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"

for name in sudo visudo; do
    test -f "zig-out/bin/$name" && test -x "zig-out/bin/$name"
done
test -L zig-out/bin/sudoedit
test "$(readlink -- zig-out/bin/sudoedit)" = sudo

if [ -n "${ZIG:-}" ]; then
    zig_version=$("$ZIG" version)
elif command -v zig >/dev/null 2>&1; then
    zig_version=$(zig version)
else
    zig_version=$(mise exec -- zig version)
fi
source_commit=${SOURCE_COMMIT:-$(git rev-parse --verify HEAD 2>/dev/null || printf unknown)}
prefix=sudo-wrapper-linux-x86_64
stage=$(mktemp -d "${TMPDIR:-/tmp}/sudo-wrapper-package.XXXXXX")
trap 'rm -rf -- "$stage"' EXIT
trap 'exit 1' HUP INT TERM
mkdir -p "$stage/$prefix/bin" zig-out/release
chmod 0755 "$stage/$prefix" "$stage/$prefix/bin"
install -m 0755 zig-out/bin/sudo zig-out/bin/visudo "$stage/$prefix/bin/"
ln -s sudo "$stage/$prefix/bin/sudoedit"
install -m 0644 README.md LICENSE "$stage/$prefix/"
printf '%s\n' "source_commit=$source_commit" "zig_version=$zig_version" \
    'target=x86_64-linux' > "$stage/$prefix/BUILD-INFO"
(
    cd "$stage/$prefix"
    sha256sum bin/sudo bin/visudo > SHA256SUMS
    chmod 0644 BUILD-INFO SHA256SUMS
)
# Stable metadata and gzip headers, while preserving the sudoedit symlink.
tar --sort=name --format=ustar --mtime='UTC 1970-01-01' \
    --owner=0 --group=0 --numeric-owner \
    -cf "$stage/archive.tar" -C "$stage" "$prefix"
gzip -n -c "$stage/archive.tar" > "zig-out/release/$prefix.tar.gz"
(
    cd zig-out/release
    sha256sum "$prefix.tar.gz" > SHA256SUMS
)
