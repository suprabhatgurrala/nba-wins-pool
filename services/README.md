# Services
This directory contains multiple `.service` files to automatically run each of the services of the application using `systemd`.

[`nbawinspool.service`](nbawinspool.service)
- Pulls latest code from main branch and deploys. Make sure to replace `path/to/deploy/dir` with the path you want the deployed code to be stored.

[`nbawinspool-webhook-listener.service`](nbawinspool-webhook-listener.service)
- Service that runs the Github webhook listener, which monitors for pushes to main and automatically fetches changes and redeploys

[`nbawinspool.service.d/shared.conf`](nbawinspool.service.d/shared.conf)
- includes some shared config for the service files to use

[`nbawinspool.service.d/input.conf`](nbawinspool.service.d/input.conf)
- shared config that requires manual edits before using

# Installing on Linux Host
## Configuration
1. Edit [`nbawinspool.service`](nbawinspool.service) and replace `path/to/deploy/dir` with the path you want the deployed code to be stored.
2. Edit [`nbawinspool.service.d/input.conf`](nbawinspool.service.d/input.conf)
    - `WorkingDirectory`- replace `path/to/deploy/dir` to the same path as [`nbawinspool.service`](nbawinspool.service), so that the services can reference the latest files
    - `Environment` sets the environment variable `GITHUB_WEBHOOK_SECRET_TOKEN` which is required by the webhook listener
      - See [Github docs](https://docs.github.com/en/webhooks/using-webhooks/creating-webhooks#creating-a-repository-webhook) for information on setting up a secret for your webhook
## Enable Services
The shell script [`enable_services.sh`](enable_services.sh) takes care of copying the service files to your systemd directory and starts the services:
```bash
sudo ./enable_services.sh
```
Note that sudo/root access is required to setup systemd configurations

## Done!
Once the services have been enabled, the app and webhook listener will be running.
