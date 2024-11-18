# Configuring Automatic Deploys on Linux Host
## Run Webhook Listener
To keep the listener running in the background, set it up as a systemd service:

1. Copy the service file (`webook_listener.service`) to `/etc/systemd/system/`
2. Start and enable the service
```bash
sudo systemctl start webhook_listener
sudo systemctl enable webhook_listener
```

## Setup Cloudflare Tunnel to expose listener to the internet

See the following Cloudflare docs to setup a tunnel
- [Create a locally-managed tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/get-started/create-local-tunnel/)
- [Setup `cloudflared` as a service](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/configure-tunnels/local-management/as-a-service/linux/)
- [Add a DNS record for the tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/routing-to-tunnel/dns/)
