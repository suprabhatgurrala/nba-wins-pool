# Services
This directory contains multiple `.service` files to setup processes via `systemd`.

## [`github_runner.service`](github_runner.service)
- This service runs a self-hosted Github runner that listens for pushes to the main branch.
- When a push to main occurs, it pulls the new code and restarts `nbawinspool.service`
- make sure to replace `</path/to/actions-runner/run.sh>` with the correct path on your machine

## [`nbawinspool.service`](nbawinspool.service)
- Runs the docker compose commands to deploy the web app
- make sure to set the working directory to the path where the github_runner.service is cloning/pulling the repo

# Initial Setup
We need to setup these services so that the Github actions can be automatically performed.

## Github runner setup
1. Set up a self-hosted Github Runner. See [this page](https://github.com/suprabhatgurrala/nba-wins-pool/settings/actions/runners/new?arch=x64&os=linux) for repo-specific instructions
  - be sure to remember the working directory that you set while configuring
  - More information can be found in [Github docs](https://docs.github.com/en/actions/hosting-your-own-runners/managing-self-hosted-runners/adding-self-hosted-runners)
2. Enable Github Runner service
  - Replace `</path/to/actions-runner/run.sh>` in [`github_runner.service`](github_runner.service) with the path where you cloned the Github runner code
  - Copy the service file to `/etc/systemd/user/github_runner.service`. Note that it needs to be under user since the Github Runner can only run as a user (and not as root/sudo)
  - Enable the service: `systemctl --user enable github_runner.service`
  - Start the service: `systemctl --user start github_runner.service`
  - You can confirm if Github can connect to the runner by checking [this page](https://github.com/suprabhatgurrala/nba-wins-pool/actions/runners?tab=self-hosted)

## NBA Wins Pool service setup
Similarly setup the NBA wins pool service:

1. Replace `<path/to/deploy/code>` with the path to the directory you configured while setting up the github runner
2. Copy the service file to `/etc/systemd/user/nbawinspool.service`
3. Tell systemd to reload from disk: `systemctl --user daemon-reload`
3. Enable the service: `systemctl --user enable nbawinspool.service`
4. Start the service: `systemctl --user start nbawinspool.service`

The production code is accessible at localhost:43565, which can be port forwarded to host publicly.

## Other setup
- See [Cloudflare tunnels](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/get-started/create-remote-tunnel/) to allow the port to be accessible without directly exposing it to the internet.
- Use `journalctl --user -u nbawinspool.service` and `journalctl --user -u github_runner.service` to monitor the logs/output from those services
