# Personal VPN on the Hetzner VPS (Sweden)

TunnelBear replacement: the VPS becomes a single WireGuard endpoint, and the
Android phone routes **all** its traffic through it, exiting to the internet
from the VPS's Swedish IP.

```
Android phone ──(encrypted WireGuard tunnel, UDP 51820)──> Hetzner VPS (SE) ──> internet
```

## One-time server setup

1. Copy `setup-wireguard.sh` to the VPS and run it as root:

   ```bash
   scp vpn/setup-wireguard.sh root@<vps-ip>:
   ssh root@<vps-ip> "bash setup-wireguard.sh"
   ```

2. It prints a QR code at the end.

3. **Hetzner Cloud Firewall**: if the VPS uses a Hetzner Cloud firewall (set in
   the Hetzner console, separate from ufw on the box), add an inbound rule
   allowing **UDP 51820** from any source. Without this the phone can't connect.

## Android setup

1. Install **WireGuard** (WireGuard Development Team) from the Play Store.
2. Tap **+** → **Scan from QR code** → scan the code from the setup script.
3. Toggle the tunnel on. Verify at https://ifconfig.me — it should show the
   VPS's IP and locate you in Sweden.
4. Optional, TunnelBear "always on" equivalent:
   Android Settings → Network → VPN → ⚙ next to WireGuard →
   enable **Always-on VPN** and **Block connections without VPN** (kill switch).

## Adding more devices

```bash
ssh root@<vps-ip> "bash add-peer.sh laptop"
```

Each device gets its own key and IP (10.66.66.x).

## Notes & troubleshooting

- **Battery**: WireGuard is very light; `PersistentKeepalive = 25` keeps the
  tunnel up behind mobile NAT with negligible drain.
- **Check server status**: `wg show` — a recent "latest handshake" means the
  phone is connected.
- **No handshake?** Almost always the firewall: check both `ufw status` on the
  box and the Hetzner Cloud firewall for UDP 51820.
- **Split tunnel**: in the Android app you can exclude apps (e.g. banking apps
  that dislike VPNs) via the tunnel's *Applications* setting — no server
  changes needed.
- **Privacy**: unlike TunnelBear you're the only user of this IP, so sites see
  a stable Hetzner address. That's fine for geo/Wi-Fi-security use; it is not
  an anonymity service.
- The client `.conf` files in `/etc/wireguard/` on the VPS contain private
  keys — don't commit them anywhere.
