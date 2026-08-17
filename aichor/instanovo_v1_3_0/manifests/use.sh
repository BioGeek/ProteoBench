#!/usr/bin/env bash
# Copy one variant's manifest to the repo root, which is the only place AIchor reads from.
#
#   ./aichor/instanovo_v1_3_0/manifests/use.sh greedy
#   git commit -am "run: v1.3.0 greedy on nine-species balanced"
#   aichor experiments submit local --repo-dir . --message "v1.3.0 greedy"
#
# INSTANOVO_INSTALL_SPEC must be filled in first -- the build fails fast while it is empty.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
root="$here/../../.."
mode="${1:?usage: use.sh <variant>}"
src="$here/${mode}.yaml"
[ -f "$src" ] || { echo "no such variant: $mode" >&2; ls "$here"/*.yaml | xargs -n1 basename >&2; exit 1; }
cp "$src" "$root/manifest.yaml"
echo "manifest.yaml <- aichor/instanovo_v1_3_0/manifests/${mode}.yaml"
grep -A3 '^  command:' "$root/manifest.yaml" | sed 's/^/  /'
spec=$(python3 -c "import yaml,sys; print(yaml.safe_load(open('$root/manifest.yaml'))['builder']['buildArgs']['INSTANOVO_INSTALL_SPEC'])")
[ -n "$spec" ] || echo "WARNING: INSTANOVO_INSTALL_SPEC is still empty; the build will fail by design." >&2
