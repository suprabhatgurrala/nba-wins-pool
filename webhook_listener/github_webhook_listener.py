import argparse
import hashlib
import hmac
import logging
import os
import subprocess

from fastapi import FastAPI, HTTPException, Request

app = FastAPI()
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

# Secret token from GitHub webhook settings (set this in your environment)
SECRET_TOKEN = os.environ["GITHUB_WEBHOOK_SECRET_TOKEN"]


def verify_signature(payload: bytes, signature: str) -> bool:
    """Verify the webhook payload using the secret token."""
    expected_signature = "sha256=" + hmac.new(SECRET_TOKEN.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected_signature, signature)


@app.get("/")
async def hello():
    return {"message": "Hello, app is running."}


@app.post("/webhook")
async def github_webhook(request: Request):
    """Handle incoming GitHub webhook requests."""
    # Retrieve headers
    signature = request.headers.get("X-Hub-Signature-256")
    event = request.headers.get("X-GitHub-Event")
    delivery_id = request.headers.get("X-GitHub-Delivery")

    # Log headers for debugging
    logger.debug(f"Received event: {event}, delivery ID: {delivery_id}")

    # Get the JSON payload
    payload = await request.body()

    # Verify signature if the secret token is set
    if SECRET_TOKEN:
        if not signature:
            raise HTTPException(status_code=400, detail="Missing signature header.")
        if not verify_signature(payload, signature):
            raise HTTPException(status_code=400, detail="Invalid signature.")

    # Parse the payload
    data = await request.json()

    # Handle the 'push' event
    if event == "push":
        branch = data.get("ref", "unknown")
        pusher = data.get("pusher", {}).get("name", "unknown")
        repository = data.get("repository", {}).get("full_name", "unknown")

        logger.debug(f"Push event received on branch {branch} in repository {repository} by {pusher}.")

        if branch == "refs/head/main":
            logger.info("Push to main branch, running deploy command")
            process = subprocess.run(["systemctl", "restart", "nbawinspool.service"])

        return {"message": "Push event handled successfully."}

    # For unsupported events
    return {"message": f"Unhandled event type: {event}"}


# Entry point for running the server
if __name__ == "__main__":
    import uvicorn

    # Parse command-line arguments for the port
    parser = argparse.ArgumentParser(description="GitHub Webhook Listener")
    parser.add_argument(
        "--port",
        type=int,
        default=55255,
        help="Port number to run the webhook listener (default: 55255)",
    )
    args = parser.parse_args()

    # Start the server on the specified port
    uvicorn.run(app, host="0.0.0.0", port=args.port)
