#!/usr/bin/env bash
set -euo pipefail

REPO="${TRAILHEAD_REPO:-/home/ubuntu/src/hermes-trailhead}"
TARGET="${TRAILHEAD_BIN:-/usr/local/bin/hermes-trailhead}"

if [[ ! -d "$REPO/hermes_trailhead" ]]; then
  echo "Trailhead package not found at $REPO/hermes_trailhead" >&2
  exit 1
fi

cat > /tmp/hermes-trailhead-wrapper <<EOF
#!/usr/bin/env bash
cd "$REPO"
exec python3 -m hermes_trailhead "\$@"
EOF

install -m 0755 /tmp/hermes-trailhead-wrapper "$TARGET"
rm -f /tmp/hermes-trailhead-wrapper
printf 'installed %s -> %s\n' "$TARGET" "$REPO"
printf 'run: hermes-trailhead doctor\n'
