# Script to copy service files and start services

# Stop service if already running
systemctl stop nbawinspool.service
systemctl disable nbawinspool.service

# Delete any existing service files
rm -rf /etc/systemd/system/nbawinspool*

# Copy service files
cp -r nbawinspool* /etc/systemd/system

# Create symbolic links so that both services can refer to same shared.conf and input.conf values
mkdir /etc/systemd/system/nbawinspool-webhook-listener.service.d
ln -s /etc/systemd/system/nbawinspool.service.d/shared.conf /etc/systemd/system/nbawinspool-webhook-listener.service.d/shared.conf
ln -s /etc/systemd/system/nbawinspool.service.d/input.conf /etc/systemd/system/nbawinspool-webhook-listener.service.d/input.conf

# Start the service
systemctl daemon-reload
systemctl enable nbawinspool.service
systemctl start nbawinspool.service
systemctl status nbawinspool.service
