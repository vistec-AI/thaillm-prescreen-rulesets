# Deployment

## Environment Variables

See the [Environment Variables](environment-variables.md) page for a comprehensive reference of every variable, including database connection pool tuning, medical thresholds, pagination defaults, and cleanup settings.

The most important variables for deployment are:

| Variable | Default | Description |
|----------|---------|-------------|
| `SERVER_HOST` | `0.0.0.0` | Bind address |
| `SERVER_PORT` | `8080` | Listen port |
| `SERVER_CORS_ORIGINS` | `*` | Comma-separated allowed origins |
| `SERVER_LOG_LEVEL` | `INFO` | Python logging level |
| `ADMIN_API_KEY` | *(none)* | Shared secret for admin endpoints |
| `TRUSTED_PROXY_SECRET` | *(none)* | Shared secret for API gateway |
| `PG_HOST` | `localhost` | PostgreSQL host |
| `PG_PORT` | `5432` | PostgreSQL port |
| `PG_USER` | `prescreen` | Database user |
| `PG_PASSWORD` | `prescreen` | Database password |
| `PG_DATABASE` | `prescreen` | Database name |

## Docker

### Single Container

The Dockerfile builds a multi-stage image:

```bash
docker build -t prescreen-server .
docker run -p 8080:8080 \
  -e PG_HOST=host.docker.internal \
  -e PG_PORT=5432 \
  -e PG_USER=prescreen \
  -e PG_PASSWORD=prescreen \
  -e PG_DATABASE=prescreen \
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

## Session Cleanup CLI

The `prescreen-cleanup` command provides a standalone tool for purging old sessions. It connects directly to the database and is suitable for cron jobs or one-off maintenance.

```bash
# Soft-delete completed/terminated sessions older than 90 days (default)
uv run prescreen-cleanup

# Permanently delete sessions older than 30 days
uv run prescreen-cleanup --days 30 --hard

# Purge all soft-deleted rows
uv run prescreen-cleanup --purge-deleted

# Purge soft-deleted rows older than 7 days
uv run prescreen-cleanup --purge-deleted --days 7

# Only target specific statuses
uv run prescreen-cleanup --status completed --status terminated
```

Options:

| Flag | Default | Description |
|------|---------|-------------|
| `--days` | `$DEFAULT_CLEANUP_DAYS` or `90` | Age threshold in days (0 = all matching sessions) |
| `--status` | `completed`, `terminated` | Session status filter (repeatable) |
| `--hard` | off | Permanently DELETE instead of soft-delete |
| `--purge-deleted` | off | Remove previously soft-deleted rows |
| `--log-level` | `INFO` | Log verbosity |

**Cron example** (purge completed sessions older than 90 days nightly):

```cron
0 3 * * * cd /app && uv run prescreen-cleanup --days 90 >> /var/log/prescreen-cleanup.log 2>&1
```

## Production Checklist

1. Set `SERVER_CORS_ORIGINS` to your specific frontend domains
2. Place an API gateway in front for authentication (see [Authentication](authentication.md))
3. **Set `TRUSTED_PROXY_SECRET`** so the server rejects requests without a valid gateway secret
4. Use a managed PostgreSQL instance with backups
5. Set `SERVER_LOG_LEVEL=WARNING` to reduce log noise
6. Configure the health check in your orchestrator
7. Ensure the `v1/` rulesets directory is available (copied into the Docker image by default)
8. Set `ADMIN_API_KEY` to enable admin cleanup endpoints
9. Schedule `prescreen-cleanup` via cron or a job scheduler to prevent unbounded table growth
