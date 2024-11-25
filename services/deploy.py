#!/usr/bin/env python3
import argparse
import atexit
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")


def main(deploy_path):
    if not deploy_path.exists():
        # Clone copy of main branch
        subprocess.run(
            [
                "git",
                "clone",
                "-b",
                "main",
                "--single-branch",
                "git@github.com:suprabhatgurrala/nba-wins-pool.git",
                deploy_path,
            ]
        )
    subprocess.run(["git", "pull"], cwd=deploy_path)
    subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            "compose.yml",
            "-f",
            "compose.prod.yml",
            "up",
            "--build",
        ],
        cwd=deploy_path,
    )


def cleanup(deploy_path):
    subprocess.run(["docker", "compose", "down", "-v"])


def entrypoint():
    parser = argparse.ArgumentParser(
        prog="NBA Wins Pool Auto-deploy", description="Script to autodeploy NBA Wins Pool app"
    )
    parser.add_argument(
        "deploy_path", help="path to store deployed code. Note that this should be separate from your development code"
    )
    args = parser.parse_args()
    deploy_path = Path(args.deploy_path).resolve()
    logger.info(f"Deploying to path: {deploy_path}")
    atexit.register(cleanup, deploy_path=deploy_path)
    main(deploy_path)


if __name__ == "main":
    entrypoint()
