# Playwright Tests
Playwright is used to run end-to-end (E2E) tests against both the frontend and backend to make sure everything is hooked up correctly.

## Running Locally
To run the tests locally:

1. Install playwright. Note that playwright requires bash for Linux based systems, so Alpine containers won't work

    ```bash
    npm install
    npx playwright install --with-deps
    ```
2. Run tests

    ```bash
    npx playwright test
    ```

    To enable debug logging:
    ```bash
    DEBUG=pw:api npx playwright test
    ```

## Running in Docker
The Dockerfile in this directory uses a Playwright image separate from frontend and backend.
See [README.md](../README.md) for instructions.
