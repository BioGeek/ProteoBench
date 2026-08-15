#!/usr/bin/env bash
# Start Triton/Koina in the background, wait for it to report ready, then exec the
# command given to the container. Adapted from instadeepai/winnow's entrypoint.koina.sh.
set -euo pipefail

KOINA_HEALTH_URL="${KOINA_HEALTH_URL:-http://localhost:8501/v2/health/ready}"
KOINA_READY_TIMEOUT_SECS="${KOINA_READY_TIMEOUT_SECS:-1800}"

# Triton's Python-backend stub derives sys.path from its own location under
# /opt/tritonserver, so it misses the dist-packages where pip put numpy/pandas/ms2pip.
# Set PYTHONPATH on the Triton invocation only: exporting it globally would also put
# those Python 3.10 packages ahead of the winnow venv's own for the foreground command.
echo "[entrypoint.koina] starting Triton/Koina in background (MODEL_PATTERN=${MODEL_PATTERN:-unset})..."
PYTHONPATH="/usr/local/lib/python3.10/dist-packages${PYTHONPATH:+:$PYTHONPATH}" \
    /models/start.py &
KOINA_PID=$!

trap 'echo "[entrypoint.koina] stopping Triton (pid $KOINA_PID)"; kill $KOINA_PID 2>/dev/null || true; wait $KOINA_PID 2>/dev/null || true' EXIT

echo "[entrypoint.koina] waiting for $KOINA_HEALTH_URL (timeout=${KOINA_READY_TIMEOUT_SECS}s) ..."
DEADLINE=$((SECONDS + KOINA_READY_TIMEOUT_SECS))
until curl -fsS "$KOINA_HEALTH_URL" >/dev/null 2>&1; do
  if ! kill -0 "$KOINA_PID" 2>/dev/null; then
    echo "[entrypoint.koina] Triton exited before becoming ready" >&2
    wait "$KOINA_PID" || true
    exit 1
  fi
  if (( SECONDS > DEADLINE )); then
    echo "[entrypoint.koina] timeout after ${KOINA_READY_TIMEOUT_SECS}s waiting for Koina readiness" >&2
    exit 1
  fi
  sleep 5
done

echo "[entrypoint.koina] Koina is ready. Running: $*"
exec "$@"
