# Playwright Tests
Playwright is used to run end-to-end (E2E) tests against both the frontend and backend to make sure everything is hooked up correctly.

## Running Locally with npm

### Prerequisites
1. Make sure the application is running (backend + frontend):
   ```bash
   # From the project root
   make dev
   ```
   The app should be accessible at `http://localhost:8000`

### Setup
1. Navigate to the playwright_tests directory:
   ```bash
   cd playwright_tests
   ```

2. Install dependencies:
   ```bash
   npm install
   ```

3. Install Playwright browsers (only needed once):
   ```bash
   npx playwright install --with-deps
   ```
   Note: Playwright requires bash for Linux-based systems, so Alpine containers won't work.

### Running Tests

Run all tests:
```bash
npm test
```

Run tests in headed mode (see the browser):
```bash
npm run test:headed
```

Run tests in UI mode (interactive):
```bash
npm run test:ui
```

Run tests in debug mode:
```bash
npm run test:debug
```

View test report:
```bash
npm run test:report
```

### Configuration
- Tests expect the app to be running at `http://localhost:8000` (default)
- To test against a different URL, set the `BASE_URL` environment variable:
  ```bash
  BASE_URL=http://localhost:5173 npm test
  ```

## Running in Docker
The Dockerfile in this directory uses a Playwright image separate from frontend and backend.
See [README.md](../README.md) for instructions or use:
```bash
# From the project root
make e2e_tests
```
