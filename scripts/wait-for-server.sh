# Sourced by start-kiosk.sh. Wait for the OpenFlight server to answer HTTP.
#
# The server brings up the camera, IWR6843 and OPS243 before Flask listens; a
# Pi 5 measured 12 s warm and 14 s cold, so the old 15 s cap tore down healthy
# servers on slower cold boots. 30 s leaves about twice the cold-boot time, and
# a crashed server still ends the wait at once.
#
# The budget is counted in polls, not read from the clock: the Pi has no RTC,
# and NTP can jump the wall clock minutes forward in the middle of startup.

OPENFLIGHT_SERVER_START_DEFAULT_S=30
OPENFLIGHT_SERVER_POLL_S=0.5

# Usage: wait_for_server URL SERVER_PID [TIMEOUT_S]
# Returns 0 once URL answers, 1 if SERVER_PID exits or the budget runs out.
wait_for_server() {
    local url="$1"
    local server_pid="$2"
    local timeout_s="${3:-${OPENFLIGHT_SERVER_START_TIMEOUT_S:-}}"
    if ! [[ "$timeout_s" =~ ^[1-9][0-9]*$ ]]; then
        timeout_s="$OPENFLIGHT_SERVER_START_DEFAULT_S"
    fi

    # Two polls per second at OPENFLIGHT_SERVER_POLL_S=0.5.
    local max_polls=$((timeout_s * 2))
    local sleeps=0
    while [ "$sleeps" -lt "$max_polls" ]; do
        if curl -fsS --max-time 2 "$url" >/dev/null 2>&1; then
            log "Server ready after ~$((sleeps / 2))s"
            return 0
        fi
        kill -0 "$server_pid" 2>/dev/null || return 1
        sleep "$OPENFLIGHT_SERVER_POLL_S"
        sleeps=$((sleeps + 1))
    done
    return 1
}
