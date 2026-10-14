#!/usr/bin/env bash
set -euo pipefail

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="${TRAILHEAD_REPO:-$(cd "$SELF_DIR/.." && pwd)}"
TARGET="${TRAILHEAD_BIN:-/usr/local/bin/hermes-trailhead}"

if [[ ! -d "$REPO/hermes_trailhead" ]]; then
  echo "Trailhead package not found at $REPO/hermes_trailhead" >&2
  exit 1
fi

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TMP_WRAPPER="$(mktemp /tmp/hermes-trailhead-wrapper.XXXXXX)"
trap 'rm -f "$TMP_WRAPPER"' EXIT
sed "s|__REPO__|$REPO|" "$SELF_DIR/hermes-trailhead-wrapper.template" \
  > "$TMP_WRAPPER"
install -m 0755 "$TMP_WRAPPER" "$TARGET"
printf 'installed %s -> %s\n' "$TARGET" "$REPO"
printf 'run: hermes-trailhead doctor\n'