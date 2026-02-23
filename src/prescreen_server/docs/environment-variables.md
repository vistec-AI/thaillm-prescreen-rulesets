# Environment Variables

All configuration is done via environment variables. Every variable has a sensible default for local development; in production you override the values via env vars or a `.env` file.

A template file `.env.example` is provided at the repository root.

---

## Server

Control the FastAPI / Uvicorn process.

| Variable | Default | Description |
|----------|---------|-------------|
| `SERVER_HOST` | `0.0.0.0` | Bind address. |
| `SERVER_PORT` | `8080` | Listen port. |
| `SERVER_CORS_ORIGINS` | `*` | Comma-separated allowed origins (e.g. `https://app.example.com,https://admin.example.com`). Use `*` only in development. |
| `SERVER_RULESET_DIR` | *(auto)* | Absolute path to the `v1/` rulesets directory. When not set, the server auto-detects it from the repository root. |
| `SERVER_LOG_LEVEL` | `INFO` | Python logging level. Accepted values: `DEBUG`, `INFO`, `WARNING`, `ERROR`. |

---

## Database

Connection settings for PostgreSQL, read by the `prescreen_db` package.

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | *(none)* | Full PostgreSQL connection URL (e.g. `postgresql://user:pass@host:5432/dbname`). When set, the individual `PG_*` variables below are ignored. |
| `PG_HOST` | `localhost` | PostgreSQL host. |
| `PG_PORT` | `5432` | PostgreSQL port. |
| `PG_USER` | `prescreen` | Database user. |
| `PG_PASSWORD` | `prescreen` | Database password. |
| `PG_DATABASE` | `prescreen` | Database name. |

### Connection Pool

Tune the SQLAlchemy async connection pool. These directly map to SQLAlchemy's `create_async_engine` parameters.

| Variable | Default | Description |
|----------|---------|-------------|
| `PG_POOL_SIZE` | `5` | Number of persistent connections kept in the pool. Increase for high-concurrency deployments. |
| `PG_MAX_OVERFLOW` | `10` | Maximum number of additional connections allowed beyond `PG_POOL_SIZE` during traffic spikes. Once the spike subsides the extra connections are closed. |

!!! tip "Sizing the pool"
    A good starting point is `PG_POOL_SIZE` = number of Uvicorn workers and `PG_MAX_OVERFLOW` = 2 x pool size. Monitor `pg_stat_activity` to see actual usage.

---

## Authentication & Security

| Variable | Default | Description |
|----------|---------|-------------|
| `ADMIN_API_KEY` | *(none)* | Shared secret for the `/api/v1/admin/*` endpoints. **Admin endpoints are disabled when this is not set.** Clients must send it in the `X-Admin-Key` header. |
| `TRUSTED_PROXY_SECRET` | *(none)* | Shared secret between the API gateway and this server. When set, every request carrying `X-User-ID` must also carry a matching `X-Proxy-Secret` header. This prevents clients from forging the user identity header. |

See the [Authentication](authentication.md) page for a full explanation of the header-based identity scheme.

---

## Medical / Domain Thresholds

These values control clinical decision logic in the prescreening engine. Override them only if your deployment uses a different clinical protocol.

| Variable | Default | Description |
|----------|---------|-------------|
| `PEDIATRIC_AGE_THRESHOLD` | `15` | Age cutoff (in years) for the pediatric ER checklist. Patients **younger than** this age receive the pediatric checklist in Phase 3; patients at or above this age receive the adult checklist. |
| `DEFAULT_ER_SEVERITY` | `sev003` | Default severity ID assigned when an ER critical item (Phase 1) or ER checklist item (Phase 3) triggers termination but does not specify an explicit severity. `sev003` = Emergency. |
| `DEFAULT_ER_DEPARTMENT` | `dept002` | Default department ID assigned under the same conditions. `dept002` = Emergency Medicine. |

!!! warning "Change with care"
    These thresholds affect clinical routing. Changing them without medical review may cause patients to be triaged incorrectly. The defaults follow standard Thai medical practice.

### Severity Level Reference

| ID | Name |
|----|------|
| `sev001` | Observe at Home |
| `sev002` | Visit Hospital / Clinic |
| `sev002_5` | Visit Hospital / Clinic Urgently |
| `sev003` | Emergency |

### Department Reference

| ID | Name |
|----|------|
| `dept001` | Dermatology |
| `dept002` | Emergency Medicine |
| `dept003` | Forensic Medicine |
| `dept004` | Internal Medicine |
| `dept005` | Obstetrics and Gynecology |
| `dept006` | Ophthalmology |
| `dept007` | Orthopedics and Physical Therapy |
| `dept008` | Otorhinolaryngology |
| `dept009` | Pediatrics |
| `dept010` | Psychiatry |
| `dept011` | Rehabilitation |
| `dept012` | Surgery |

---

## Pagination

Control the default and maximum page sizes for list endpoints (e.g. `GET /api/v1/sessions`).

| Variable | Default | Description |
|----------|---------|-------------|
| `DEFAULT_PAGE_LIMIT` | `20` | Default number of items returned per page when the client does not specify a `limit` query parameter. |
| `MAX_PAGE_LIMIT` | `100` | Maximum allowed value for the `limit` query parameter. Requests exceeding this are clamped. |

---

## Session Cleanup

Control the automatic and manual cleanup of old sessions.

| Variable | Default | Description |
|----------|---------|-------------|
| `SESSION_TTL_DAYS` | `0` | Default age threshold (days) used by the server-side TTL. `0` means infinite — no automatic cleanup unless explicitly requested via the admin endpoint or CLI. |
| `DEFAULT_CLEANUP_DAYS` | `90` | Default value for the `older_than_days` parameter on the admin cleanup endpoint (`POST /api/v1/admin/cleanup/sessions`) and the `--days` flag on the `prescreen-cleanup` CLI. Sessions older than this many days are affected. |

The cleanup CLI (`prescreen-cleanup`) resolves its `--days` default in this order:

1. `DEFAULT_CLEANUP_DAYS` env var
2. `SESSION_TTL_DAYS` env var (fallback)
3. `90` (hardcoded fallback)

---

## Quick Reference

All variables in one table:

| Variable | Default | Category |
|----------|---------|----------|
| `SERVER_HOST` | `0.0.0.0` | Server |
| `SERVER_PORT` | `8080` | Server |
| `SERVER_CORS_ORIGINS` | `*` | Server |
| `SERVER_RULESET_DIR` | *(auto)* | Server |
| `SERVER_LOG_LEVEL` | `INFO` | Server |
| `DATABASE_URL` | *(none)* | Database |
| `PG_HOST` | `localhost` | Database |
| `PG_PORT` | `5432` | Database |
| `PG_USER` | `prescreen` | Database |
| `PG_PASSWORD` | `prescreen` | Database |
| `PG_DATABASE` | `prescreen` | Database |
| `PG_POOL_SIZE` | `5` | Database |
| `PG_MAX_OVERFLOW` | `10` | Database |
| `ADMIN_API_KEY` | *(none)* | Auth |
| `TRUSTED_PROXY_SECRET` | *(none)* | Auth |
| `PEDIATRIC_AGE_THRESHOLD` | `15` | Medical |
| `DEFAULT_ER_SEVERITY` | `sev003` | Medical |
| `DEFAULT_ER_DEPARTMENT` | `dept002` | Medical |
| `DEFAULT_PAGE_LIMIT` | `20` | Pagination |
| `MAX_PAGE_LIMIT` | `100` | Pagination |
| `SESSION_TTL_DAYS` | `0` | Cleanup |
| `DEFAULT_CLEANUP_DAYS` | `90` | Cleanup |
