#!/bin/bash
set -e

# ==============================================================================
# Staemme Bot Container Entrypoint
#
# Starts Xvfb (virtual display), optional VNC server, then the bot.
# Xvfb is preferred over true headless — identical rendering preserves stealth.
# ==============================================================================

# Configuration via environment variables
DISPLAY_NUM="${DISPLAY_NUM:-99}"
SCREEN_RESOLUTION="${SCREEN_RESOLUTION:-1280x720x24}"
VNC_ENABLED="${VNC_ENABLED:-true}"
VNC_PORT="${VNC_PORT:-5900}"
VNC_PASSWORD="${VNC_PASSWORD:-}"
PROFILE="${PROFILE:-default}"
API_PORT="${API_PORT:-8000}"

export DISPLAY=":${DISPLAY_NUM}"

echo "=== Staemme Bot Starting ==="
echo "Profile: ${PROFILE}"
echo "Display: ${DISPLAY}"
echo "Resolution: ${SCREEN_RESOLUTION}"
echo "VNC: ${VNC_ENABLED}"
echo "API Port: ${API_PORT}"

# ---------------------------------------------------------------------------
# 1. Start Xvfb (virtual X11 display)
# ---------------------------------------------------------------------------
echo "Starting Xvfb on display ${DISPLAY}..."
Xvfb "${DISPLAY}" -screen 0 "${SCREEN_RESOLUTION}" -ac -nolisten tcp &
XVFB_PID=$!

# Wait for Xvfb to be ready
for i in $(seq 1 10); do
    if xdpyinfo -display "${DISPLAY}" >/dev/null 2>&1; then
        echo "Xvfb ready"
        break
    fi
    sleep 0.5
done

# ---------------------------------------------------------------------------
# 2. Start VNC server (optional — for login / captcha solving)
# ---------------------------------------------------------------------------
if [ "${VNC_ENABLED}" = "true" ]; then
    echo "Starting x11vnc on port ${VNC_PORT}..."
    VNC_ARGS="-display ${DISPLAY} -forever -shared -rfbport ${VNC_PORT} -noxdamage"

    if [ -n "${VNC_PASSWORD}" ]; then
        mkdir -p /home/staemme/.vnc
        x11vnc -storepasswd "${VNC_PASSWORD}" /home/staemme/.vnc/passwd
        VNC_ARGS="${VNC_ARGS} -rfbauth /home/staemme/.vnc/passwd"
    else
        VNC_ARGS="${VNC_ARGS} -nopw"
    fi

    x11vnc ${VNC_ARGS} &
    VNC_PID=$!
    echo "VNC server started (PID: ${VNC_PID})"
fi

# ---------------------------------------------------------------------------
# 3. Graceful shutdown handler
# ---------------------------------------------------------------------------
shutdown() {
    echo "Received shutdown signal..."

    # Tell the bot to stop gracefully via API
    curl -s -X POST "http://localhost:${API_PORT}/api/control/stop" || true
    sleep 2

    # Kill child processes
    [ -n "${BOT_PID}" ] && kill "${BOT_PID}" 2>/dev/null
    [ -n "${VNC_PID}" ] && kill "${VNC_PID}" 2>/dev/null
    [ -n "${XVFB_PID}" ] && kill "${XVFB_PID}" 2>/dev/null

    wait
    echo "Shutdown complete"
    exit 0
}

trap shutdown SIGTERM SIGINT

# ---------------------------------------------------------------------------
# 4. Start the bot
# ---------------------------------------------------------------------------
echo "Starting Staemme bot (profile: ${PROFILE}, port: ${API_PORT})..."
cd /app

python -m staemme \
    --profile "${PROFILE}" \
    --headless \
    --api-port "${API_PORT}" &
BOT_PID=$!

echo "Bot started (PID: ${BOT_PID})"

# Wait for the bot process (or signal)
wait "${BOT_PID}"
EXIT_CODE=$?

echo "Bot exited with code ${EXIT_CODE}"

# Cleanup
[ -n "${VNC_PID}" ] && kill "${VNC_PID}" 2>/dev/null
[ -n "${XVFB_PID}" ] && kill "${XVFB_PID}" 2>/dev/null

exit "${EXIT_CODE}"
