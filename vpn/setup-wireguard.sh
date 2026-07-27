#!/usr/bin/env bash
#
# WireGuard VPN server setup for the Hetzner VPS (Sweden).
#
# Turns the VPS into a personal VPN endpoint: your Android phone connects
# with the official WireGuard app and ALL its traffic exits via the VPS's
# Swedish IP address (TunnelBear-style, single endpoint).
#
# Usage (run ON the VPS, as root):
#   sudo bash setup-wireguard.sh
#
# It will:
#   1. Install wireguard + qrencode
#   2. Generate server + one Android peer keypair
#   3. Configure wg0 (10.66.66.0/24), enable IP forwarding + NAT
#   4. Open UDP 51820 in the firewall (ufw, if present)
#   5. Print the Android client config as a QR code to scan
#
# Re-running is safe only on a fresh box; it refuses to overwrite an
# existing /etc/wireguard/wg0.conf.

set -euo pipefail

WG_PORT="${WG_PORT:-51820}"
WG_NET="10.66.66"
DNS="${WG_DNS:-1.1.1.1, 1.0.0.1}"
CLIENT_NAME="${CLIENT_NAME:-android}"

if [[ $EUID -ne 0 ]]; then
  echo "Run as root: sudo bash $0" >&2
  exit 1
fi

if [[ -f /etc/wireguard/wg0.conf ]]; then
  echo "/etc/wireguard/wg0.conf already exists — refusing to overwrite." >&2
  echo "To add another device instead, use add-peer.sh." >&2
  exit 1
fi

echo "==> Installing WireGuard..."
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq wireguard qrencode iptables

# Public IP and default egress interface
SERVER_IP="$(curl -4 -fsS https://ifconfig.me || curl -4 -fsS https://api.ipify.org)"
EGRESS_IF="$(ip -4 route show default | awk '{print $5; exit}')"
echo "==> Server public IP: ${SERVER_IP}, egress interface: ${EGRESS_IF}"

echo "==> Generating keys..."
umask 077
mkdir -p /etc/wireguard
SERVER_PRIV="$(wg genkey)"
SERVER_PUB="$(echo "${SERVER_PRIV}" | wg pubkey)"
CLIENT_PRIV="$(wg genkey)"
CLIENT_PUB="$(echo "${CLIENT_PRIV}" | wg pubkey)"
CLIENT_PSK="$(wg genpsk)"

echo "==> Writing /etc/wireguard/wg0.conf..."
cat > /etc/wireguard/wg0.conf <<EOF
[Interface]
Address = ${WG_NET}.1/24
ListenPort = ${WG_PORT}
PrivateKey = ${SERVER_PRIV}
# NAT phone traffic out via the VPS's public interface
PostUp   = iptables -t nat -A POSTROUTING -s ${WG_NET}.0/24 -o ${EGRESS_IF} -j MASQUERADE; iptables -A FORWARD -i wg0 -j ACCEPT; iptables -A FORWARD -o wg0 -j ACCEPT
PostDown = iptables -t nat -D POSTROUTING -s ${WG_NET}.0/24 -o ${EGRESS_IF} -j MASQUERADE; iptables -D FORWARD -i wg0 -j ACCEPT; iptables -D FORWARD -o wg0 -j ACCEPT

# ${CLIENT_NAME}
[Peer]
PublicKey = ${CLIENT_PUB}
PresharedKey = ${CLIENT_PSK}
AllowedIPs = ${WG_NET}.2/32
EOF

echo "==> Enabling IP forwarding..."
cat > /etc/sysctl.d/99-wireguard.conf <<EOF
net.ipv4.ip_forward=1
EOF
sysctl -p /etc/sysctl.d/99-wireguard.conf >/dev/null

if command -v ufw >/dev/null 2>&1 && ufw status | grep -q "Status: active"; then
  echo "==> Opening UDP ${WG_PORT} in ufw..."
  ufw allow "${WG_PORT}/udp" >/dev/null
fi

echo "==> Starting WireGuard..."
systemctl enable --now wg-quick@wg0

# Android client config
CLIENT_CONF="/etc/wireguard/${CLIENT_NAME}.conf"
cat > "${CLIENT_CONF}" <<EOF
[Interface]
PrivateKey = ${CLIENT_PRIV}
Address = ${WG_NET}.2/32
DNS = ${DNS}

[Peer]
PublicKey = ${SERVER_PUB}
PresharedKey = ${CLIENT_PSK}
Endpoint = ${SERVER_IP}:${WG_PORT}
# Route ALL traffic through the VPN (full-tunnel, TunnelBear-style)
AllowedIPs = 0.0.0.0/0, ::/0
# Keeps the tunnel alive behind mobile NAT
PersistentKeepalive = 25
EOF

echo
echo "============================================================"
echo " Done. Scan this QR code with the WireGuard Android app:"
echo " (app: 'WireGuard' by WireGuard Development Team, Play Store)"
echo "============================================================"
qrencode -t ansiutf8 < "${CLIENT_CONF}"
echo
echo "Client config also saved at: ${CLIENT_CONF}"
echo "Check status with: wg show"
