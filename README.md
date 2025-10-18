# nba-wins-pool
website to display the standings of an NBA Wins Pool

## Development

# Setup
Run `pre-commit install` to setup commit hooks

Links:
* [backend README](./backend/README.md)
* [frontend README](./frontend/README.md)

## Running with Docker Compose
This project uses docker-compose to coordinate spinning up containers for the python web app, database, etc.

### Run App in Developer Mode
The following command will spin up containers for frontend and backend development servers:

```bash
docker-compose up --build --watch
```
- `--build` - tells docker to rebuild the base image
- `--watch` - enables hot-reloading when files are changed

Or use the make command:
```bash
make dev
```

Navigate to `localhost:8080` to interact with the frontend

### Run App in Production
The following command will build the frontend application and make the distribution files available to the backend, which will serve them directly.

```bash
docker-compose -f compose.yml -f compose.prod.yml up --build
```

Or use the make command:
```bash
make prod
```

Navigate to `localhost:43565` to interact with the frontend


### Shut down
This will remove the containers and volumes
```bash
docker-compose down -v
```
- `-v` - remove created volumes

Or use the make command:
```bash
make down
```

### Tests
For backend unit tests:
```bash
make backend_test
```

For Playwright E2E tests:
```bash
make e2e_tests
```

## License

This project is licensed under the **GNU Affero General Public License v3.0 (AGPL-3.0)**.

This means:
- ✅ You can use, modify, and distribute this software
- ✅ Source code must be made available to users
- ✅ Any modifications must also be licensed under AGPL-3.0
- ❌ **Commercial use requires releasing your source code** under AGPL-3.0
- ❌ Cannot be used in proprietary/closed-source commercial products

The AGPL-3.0 license is specifically designed for network services and web applications. If you run a modified version of this software as a service, you must provide the source code to your users.

See the [LICENSE](./LICENSE) file for the full license text.
