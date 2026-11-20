#!/bin/sh
set -eu
log() { echo "[playwright-loophole] $*"; }
fail() { echo "[playwright-loophole] ERROR: $*" >&2; exit 1; }

# Import trust even when forwarding is disabled or the host shares our namespace.
if [ -n "${LOOPHOLE_CA_CERT_B64:-}" ]; then
    CA_CERT=$(mktemp)
    trap 'rm -f "$CA_CERT"' EXIT
    printf '%s' "$LOOPHOLE_CA_CERT_B64" | base64 -d > "$CA_CERT" \
        || fail "LOOPHOLE_CA_CERT_B64 is not valid base64"
else
    CA_CERT=${LOOPHOLE_CA_CERT:-/usr/local/share/ca-certificates/localias.crt}
    if [ -n "${LOOPHOLE_CA_CERT:-}" ] && [ ! -f "$CA_CERT" ]; then
        fail "LOOPHOLE_CA_CERT does not exist: $CA_CERT"
    fi
fi
EXTERNAL_CA=0
if [ -f "$CA_CERT" ]; then
    /usr/local/bin/loophole-trust-ca "$CA_CERT"
    EXTERNAL_CA=1
fi
if [ -n "${LOOPHOLE_CA_CERT_B64:-}" ]; then
    rm -f "$CA_CERT"
    trap - EXIT
fi

[ "$#" -gt 0 ] || fail 'No command supplied.'
if [ "${LOOPHOLE_ENABLED:-1}" = 0 ]; then
    log 'LOOPHOLE_ENABLED=0; skipping loopback proxy.'
    exec "$@"
fi
if [ -n "${LOOPHOLE_MAP:-}${LOOPHOLE_MAP_FILE:-}" ]; then
    if [ "$EXTERNAL_CA" = 0 ]; then
        [ "$(id -u)" = 0 ] || fail 'Container-managed localias requires root; run without --user pwuser.'
        log 'Mode: container-managed localias (direct upstreams).'
        exec /usr/bin/python3 /usr/local/lib/loophole/runtime.py managed "$@"
    fi
    log 'External CA supplied; ignoring LOOPHOLE_MAP/LOOPHOLE_MAP_FILE.'
fi
log 'Mode: host relay.'
HTTP_PORT=${LOOPHOLE_HTTP_PORT:-80}
HTTPS_PORT=${LOOPHOLE_HTTPS_PORT:-443}
for port in "$HTTP_PORT" "$HTTPS_PORT"; do
    case "$port" in ''|*[!0-9]*|??????*) fail "Invalid TCP port: $port" ;; esac
    [ "$port" -gt 0 ] && [ "$port" -le 65535 ] || fail "Invalid TCP port: $port"
done
[ "$HTTP_PORT" != "$HTTPS_PORT" ] || fail 'HTTP and HTTPS ports must differ.'
HOST_IP=${LOOPHOLE_TARGET_IP:-}
if [ -z "$HOST_IP" ]; then
    HOST_IP=$(getent ahostsv4 host.docker.internal 2>/dev/null | awk 'NR == 1 {print $1}')
fi
if [ -z "$HOST_IP" ]; then
    HOST_IP=$(ip -4 route show default 2>/dev/null | awk 'NR == 1 {print $3}')
fi
[ -n "$HOST_IP" ] || fail 'Cannot discover host. Set LOOPHOLE_TARGET_IP or add host.docker.internal:host-gateway.'
# Validate literal addresses before interpolating HAProxy configuration.
/usr/bin/python3 -c 'import ipaddress, sys; ipaddress.ip_address(sys.argv[1])' "$HOST_IP" || fail "Invalid host IP: $HOST_IP"
case "$HOST_IP" in
    127.*|::1|::ffff:127.*) log "Host resolves to loopback ($HOST_IP); skipping proxy."; exec "$@" ;;
esac
case "$HOST_IP" in *:*) TARGET="[$HOST_IP]" ;; *) TARGET=$HOST_IP ;; esac
RUNTIME_DIR=$(mktemp -d /tmp/loophole.XXXXXXXX)
PROXY_PID=''
COMMAND_PID=''
cleanup() {
    trap - EXIT
    if [ -n "$PROXY_PID" ]; then kill -TERM "$PROXY_PID" 2>/dev/null || true; fi
    rm -rf "$RUNTIME_DIR"
}
forward() {
    if [ -n "$COMMAND_PID" ]; then kill -"$1" "$COMMAND_PID" 2>/dev/null || true; fi
    if [ -n "$PROXY_PID" ]; then kill -"$1" "$PROXY_PID" 2>/dev/null || true; fi
}
trap cleanup EXIT
trap 'forward TERM' TERM
trap 'forward INT' INT
IPV6_HTTP=''
IPV6_HTTPS=''
if [ -r /proc/net/if_inet6 ] && grep -q '^00000000000000000000000000000001 ' /proc/net/if_inet6; then
    IPV6_HTTP="bind [::1]:$HTTP_PORT v6only"
    IPV6_HTTPS="bind [::1]:$HTTPS_PORT v6only"
fi
cat > "$RUNTIME_DIR/haproxy.cfg" <<CONFIG
global
    maxconn 4096
defaults
    mode tcp
    timeout connect 5s
    timeout client 1h
    timeout server 1h
frontend loophole_http
    bind 127.0.0.1:$HTTP_PORT
    $IPV6_HTTP
    default_backend host_http
backend host_http
    server localias_http $TARGET:$HTTP_PORT
frontend loophole_https
    bind 127.0.0.1:$HTTPS_PORT
    $IPV6_HTTPS
    default_backend host_https
backend host_https
    server localias_https $TARGET:$HTTPS_PORT
CONFIG
# Daemon mode acknowledges successful listener binding before returning.
haproxy -f "$RUNTIME_DIR/haproxy.cfg" -D -p "$RUNTIME_DIR/haproxy.pid"
PROXY_PID=$(cat "$RUNTIME_DIR/haproxy.pid")
log "Forwarding 127.0.0.1${IPV6_HTTP:+ and [::1]} ports $HTTP_PORT/$HTTPS_PORT -> $HOST_IP"
# monitor both processes, including unexpected proxy exit
status=0
/usr/bin/python3 /usr/local/lib/loophole/runtime.py relay "$PROXY_PID" "$@" &
COMMAND_PID=$!
while :; do
    wait "$COMMAND_PID" && status=0 || status=$?
    kill -0 "$COMMAND_PID" 2>/dev/null || break
done
exit "$status"
