#!/usr/bin/env bash
#
# Add another device (laptop, tablet, second phone) to the WireGuard server.
#
# Usage (on the VPS, as root):
#   sudo bash add-peer.sh <name>
#
# Picks the next free 10.66.66.x address, appends the peer to wg0.conf,
# hot-loads it, and prints a QR code for the new device.

set -euo pipefail

WG_CONF="/etc/wireguard/wg0.conf"
WG_NET="10.66.66"
DNS="${WG_DNS:-1.1.1.1, 1.0.0.1}"
NAME="${1:?Usage: add-peer.sh <name>}"

[[ $EUID -eq 0 ]] || { echo "Run as root." >&2; exit 1; }
[[ -f "${WG_CONF}" ]] || { echo "No ${WG_CONF} — run setup-wireguard.sh first." >&2; exit 1; }

# Next free host address (server is .1)
for i in $(seq 2 254); do
  if ! grep -q "${WG_NET}.${i}/32" "${WG_CONF}"; then
    OCTET="${i}"
    break
  fi
done

SERVER_PUB="$(awk '/^PrivateKey/ {print $3; exit}' "${WG_CONF}" | wg pubkey)"
SERVER_IP="$(curl -4 -fsS https://ifconfig.me)"
PORT="$(awk '/^ListenPort/ {print $3; exit}' "${WG_CONF}")"

umask 077
PRIV="$(wg genkey)"
PUB="$(echo "${PRIV}" | wg pubkey)"
PSK="$(wg genpsk)"

cat >> "${WG_CONF}" <<EOF

# ${NAME}
[Peer]
PublicKey = ${PUB}
PresharedKey = ${PSK}
AllowedIPs = ${WG_NET}.${OCTET}/32
EOF

wg syncconf wg0 <(wg-quick strip wg0)

CONF="/etc/wireguard/${NAME}.conf"
cat > "${CONF}" <<EOF
[Interface]
PrivateKey = ${PRIV}
Address = ${WG_NET}.${OCTET}/32
DNS = ${DNS}

[Peer]
PublicKey = ${SERVER_PUB}
PresharedKey = ${PSK}
Endpoint = ${SERVER_IP}:${PORT}
AllowedIPs = 0.0.0.0/0, ::/0
PersistentKeepalive = 25
EOF

echo "Peer '${NAME}' added at ${WG_NET}.${OCTET}. Scan:"
qrencode -t ansiutf8 < "${CONF}"
echo "Config saved at ${CONF}"
