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

## LLM Backend Hosting

### OpenAI / OpenRouter

The default `PREDICTOR_BACKEND=openai` reads `OPENAI_API_KEY` or `OPENROUTER_API_KEY` — no additional infrastructure is needed beyond the API key. See [Environment Variables — OpenAI Backend](environment-variables.md#openai-backend) for details.

### Medgemma Backend (self-hosted vLLM)

The medgemma predictor is a separate vLLM process that the API server talks to over HTTP using the OpenAI-compatible chat-completions schema. You run it alongside the API server and point the server at it via `VLLM_PREDICTOR_URL`.

**Start the vLLM container:**

```bash
docker run -it --gpus '"device=$DEVICE_CONFIG"' \
  --shm-size=32G \
  --name=prescreen-classifier \
  --ipc=host \
  -e HF_TOKEN=$HF_TOKEN \
  vllm/vllm-openai:latest \
  --model google/medgemma-27b-text-it \
  --enable-lora \
  --lora-modules prescreen=ThaiLLM/ThaiLLM-27B-Prescreen \
  --max-lora-rank 64 \
  --tensor-parallel-size $N_GPU
```

!!! note "Expose the port"
    vLLM listens on port 8000 inside the container but the command above does not publish it. Add `-p 8000:8000` (or run with `--network host`) so the prescreen API server can reach the endpoint.

**Placeholder reference:**

| Placeholder | Meaning |
|-------------|---------|
| `$DEVICE_CONFIG` | CUDA device IDs to expose to the container (e.g. `0` for single-GPU, `0,1,2,3` for 4-way TP) |
| `$HF_TOKEN` | Hugging Face access token with read access to `google/medgemma-27b-text-it` and `ThaiLLM/ThaiLLM-27B-Prescreen` |
| `$N_GPU` | Tensor-parallel size — must match the number of device IDs in `$DEVICE_CONFIG` |

**Point the API server at the predictor:**

```bash
export PREDICTOR_BACKEND=medgemma
export VLLM_PREDICTOR_URL=http://<host>:8000/v1/chat/completions
export VLLM_PREDICTOR_MODEL=prescreen   # LoRA adapter name from --lora-modules above
# export VLLM_APIKEY=...                # only if you front the predictor with an auth proxy
```

!!! warning "Model name must match the LoRA adapter"
    `--lora-modules prescreen=ThaiLLM/ThaiLLM-27B-Prescreen` registers a LoRA adapter named `prescreen`. The API server must send `"model": "prescreen"` in every request body so vLLM routes through the fine-tuned weights. The default value of `VLLM_PREDICTOR_MODEL` in code is the base model (`google/medgemma-27b-text-it`) — operators **must override it to `prescreen`** when using the LoRA adapter.

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
10. If using the medgemma backend, deploy the vLLM container separately, set `VLLM_PREDICTOR_URL` to its endpoint, and place it on the same VPC as the API server
