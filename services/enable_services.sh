systemctl stop nbawinspool.service
systemctl disable nbawinspool.service
rm -rf /etc/systemd/system/nbawinspool*
cp -r nbawinspool* /etc/systemd/system
mkdir /etc/systemd/system/nbawinspool-webhook-listener.service.d
ln -s /etc/systemd/system/nbawinspool.service.d/shared.conf /etc/systemd/system/nbawinspool-webhook-listener.service.d/shared.conf
ln -s /etc/systemd/system/nbawinspool.service.d/input.conf /etc/systemd/system/nbawinspool-webhook-listener.service.d/input.conf
systemctl daemon-reload
systemctl enable nbawinspool.service
systemctl start nbawinspool.service
systemctl status nbawinspool.service
