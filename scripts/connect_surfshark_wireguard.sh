#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${SURFSHARK_WG_CONFIG:-}" ]]; then
  echo "::error::SURFSHARK_WG_CONFIG secret is missing or empty"
  exit 1
fi

before_ip="$(curl -4fsS --max-time 15 https://api.ipify.org || true)"

if ! command -v wg-quick >/dev/null 2>&1; then
  sudo apt-get update -qq
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq wireguard-tools
fi

sudo install -d -m 700 /etc/wireguard
printf '%s\n' "$SURFSHARK_WG_CONFIG" | tr -d '\r' | sudo tee /etc/wireguard/surfshark.conf >/dev/null
sudo chmod 600 /etc/wireguard/surfshark.conf

# Keep the runner's existing DNS resolver. This avoids wg-quick depending on resolvconf.
sudo sed -i '/^[[:space:]]*DNS[[:space:]]*=/d' /etc/wireguard/surfshark.conf

sudo wg-quick up surfshark
sleep 2

after_ip="$(curl -4fsS --max-time 15 https://api.ipify.org || true)"
if [[ -z "$after_ip" ]]; then
  echo "::error::WireGuard came up but no public IPv4 address could be verified"
  sudo wg show || true
  exit 1
fi

if [[ -n "$before_ip" && "$before_ip" == "$after_ip" ]]; then
  echo "::error::Public IPv4 did not change after enabling Surfshark"
  sudo wg show || true
  exit 1
fi

{
  echo "VPN_CONNECTED=true"
  echo "VPN_BEFORE_IP=$before_ip"
  echo "VPN_EXIT_IP=$after_ip"
} >> "$GITHUB_ENV"

echo "Surfshark WireGuard connected and the runner public IPv4 changed."
sudo wg show
