# Authentication

The API uses a simple header-based identity scheme via the `X-User-ID` header.

## How It Works

Most endpoints require the `X-User-ID` header to identify the caller. This is not a security token — it's a user identity string that scopes sessions to a particular user. In production, an API gateway or reverse proxy should authenticate the request and inject this header.

```
Client ──► API Gateway (auth) ──► Prescreen API
                                  reads X-User-ID
```

## Which Endpoints Need It

| Header | Endpoints |
|--------|-----------|
| `X-User-ID` | All `/api/v1/sessions/*` endpoints (create, get, list, delete, step, LLM) |
| `X-Admin-Key` | All `/api/v1/admin/*` endpoints (bulk cleanup, purge) |
| Neither | `/health`, `/api/v1/reference/*`, `/docs`, `/redoc`, `/guide/` |

## Sending the Header

=== "curl"

    ```bash
    curl http://localhost:8080/api/v1/sessions \
      -H "X-User-ID: patient-123"
    ```

=== "Python"

    ```python
    import httpx

    client = httpx.Client(
        base_url="http://localhost:8080",
        headers={"X-User-ID": "patient-123"},
    )
    resp = client.get("/api/v1/sessions")
    ```

=== "JavaScript"

    ```javascript
    const resp = await fetch("http://localhost:8080/api/v1/sessions", {
      headers: { "X-User-ID": "patient-123" },
    });
    ```

## Missing Header — 401 Error

If you omit the `X-User-ID` header on a protected endpoint, the server returns a **401 Unauthorized**:

```json
{
  "detail": "X-User-ID header is required"
}
```

## Session Scoping

Sessions are scoped to the `(user_id, session_id)` pair. This means:

- User A cannot access User B's sessions
- The same `session_id` string can exist for different users without conflict
- Listing sessions (`GET /api/v1/sessions`) only returns sessions for the current `X-User-ID`

## Admin Endpoints — `X-Admin-Key`

The `/api/v1/admin/*` endpoints (bulk cleanup and purge) are protected by a shared secret. Set the `ADMIN_API_KEY` environment variable and pass it as the `X-Admin-Key` header:

```bash
curl -X POST "http://localhost:8080/api/v1/admin/cleanup/sessions?older_than_days=90" \
  -H "X-Admin-Key: my-secret-key"
```

| Scenario | Response |
|----------|----------|
| `ADMIN_API_KEY` not configured | 403 — admin endpoints disabled |
| `X-Admin-Key` header missing | 401 |
| `X-Admin-Key` does not match | 403 |
| Valid key | Request proceeds |

## Production Recommendations

In production, do **not** rely on the client to self-report `X-User-ID`. Instead:

1. Place an API gateway (e.g. Kong, AWS API Gateway, Nginx) in front of the Prescreen API
2. The gateway authenticates the request (JWT, OAuth, API key, etc.)
3. The gateway extracts the verified user identity and sets the `X-User-ID` header
4. The Prescreen API trusts the header because it only accepts traffic from the gateway

This keeps the Prescreen API simple and stateless while delegating auth to the gateway.

For admin endpoints, store the `ADMIN_API_KEY` securely (e.g. in a secrets manager) and only expose admin routes to internal networks or trusted operators.
