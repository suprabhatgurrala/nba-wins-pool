# Configuring Automatic Deploys on Linux Host

To keep the listener running in the background, set it up as a systemd service:

1. Copy the service file (`webook_listener.service`) to `/etc/systemd/system/`
2. Start and enable the service
```bash
sudo systemctl start webhook_listener
sudo systemctl enable webhook_listener
```
