# Github Webhook Listener
A simple python script to listen for Github webhooks whenever a push is made to main and re-deploy the services.

See [Github docs](https://docs.github.com/en/webhooks/using-webhooks/creating-webhooks#creating-a-repository-webhook) for information on setting up a webhook for your repo.

The script also supports webhook secrets and validates using HMAC verification.

# Running the Webhook Listener
See [`services/README.md`](services/README.md) for information on running the webhook listener

# Expose listener to the internet
Cloudflare tunnel is a simple way to expose the listener without needing to directly expose ports to the internet.

See the [Cloudflare docs](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/get-started/create-remote-tunnel/) for instructions to setup a tunnel

# Testing
- You can hit [Github's API](https://docs.github.com/en/rest/repos/webhooks?apiVersion=2022-11-28#test-the-push-repository-webhook) to send a test push to verify that the script is working
