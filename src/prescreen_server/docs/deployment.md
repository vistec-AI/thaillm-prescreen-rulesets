# Deployment

## Environment Variables

### Server Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `SERVER_HOST` | `0.0.0.0` | Bind address |
| `SERVER_PORT` | `8080` | Listen port |
| `SERVER_CORS_ORIGINS` | `*` | Comma-separated allowed origins (e.g. `https://app.example.com,https://admin.example.com`) |
| `SERVER_RULESET_DIR` | (auto) | Path to the `v1/` rulesets directory. Auto-detected from the repository root when not set. |
| `SERVER_LOG_LEVEL` | `INFO` | Python logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |

### Database Settings

These are read by the `prescreen_db` package:

| Variable | Default | Description |
|----------|---------|-------------|
| `PG_HOST` | `localhost` | PostgreSQL host |
| `PG_PORT` | `5432` | PostgreSQL port |
| `PG_USER` | `postgres` | Database user |
| `PG_PASS` | `postgres` | Database password |
| `PG_DB` | `prescreen` | Database name |

## Docker

### Single Container

The Dockerfile builds a multi-stage image:

```bash
docker build -t prescreen-server .
docker run -p 8080:8080 \
  -e PG_HOST=host.docker.internal \
  -e PG_PORT=5432 \
  -e PG_USER=postgres \
  -e PG_PASS=postgres \
  -e PG_DB=prescreen \
  prescreen-server
```

The container automatically runs Alembic migrations at startup before starting the server.

### Docker Compose (Full Stack)

```bash
docker compose up --build
```

This starts:

- **PostgreSQL** — database for session persistence
- **Prescreen API** — the API server (port 8080)

The server waits for the database to be ready, runs migrations, and then starts.

## Database Migrations

The server uses Alembic for schema migrations. In the Docker setup, migrations run automatically at container startup.

For manual migration management:

```bash
# Run pending migrations
cd src/prescreen_db && uv run alembic upgrade head

# Check current migration status
cd src/prescreen_db && uv run alembic current

# Generate a new migration after model changes
cd src/prescreen_db && uv run alembic revision --autogenerate -m "description"
```

## CORS Configuration

By default, CORS allows all origins (`*`), which is suitable for development. In production, restrict origins:

```bash
export SERVER_CORS_ORIGINS="https://app.example.com,https://admin.example.com"
```

## Health Check

The `/health` endpoint verifies database connectivity:

```bash
curl http://localhost:8080/health
```

```json
{"status": "ok"}
```

Use this for:

- **Kubernetes readiness probes:** `httpGet` on `/health`
- **Docker health checks:** `HEALTHCHECK CMD curl -f http://localhost:8080/health`
- **Load balancer health checks**

## Production Checklist

1. Set `SERVER_CORS_ORIGINS` to your specific frontend domains
2. Place an API gateway in front for authentication (see [Authentication](authentication.md))
3. Use a managed PostgreSQL instance with backups
4. Set `SERVER_LOG_LEVEL=WARNING` to reduce log noise
5. Configure the health check in your orchestrator
6. Ensure the `v1/` rulesets directory is available (copied into the Docker image by default)
