# Error Handling

All errors return a JSON response with a `detail` field describing the problem.

## Error Response Shape

```json
{
  "detail": "Human-readable error message"
}
```

## Status Code Mapping

| Status Code | Meaning | When |
|-------------|---------|------|
| **400** | Bad Request | Invalid answer format, wrong pipeline stage (e.g. submitting a step answer during `llm_questioning`) |
| **401** | Unauthorized | Missing `X-User-ID` header |
| **404** | Not Found | Session not found, unknown resource ID |
| **409** | Conflict | Duplicate session (same `user_id` + `session_id` already exists) |
| **422** | Validation Error | Request body doesn't match the expected Pydantic schema |
| **500** | Internal Server Error | Unexpected server-side error |

## Common Scenarios

### Missing X-User-ID Header

```bash
curl http://localhost:8080/api/v1/sessions
# 401
```

```json
{"detail": "X-User-ID header is required"}
```

**Fix:** Add the `X-User-ID` header to every session/step/LLM request.

### Session Not Found

```bash
curl http://localhost:8080/api/v1/sessions/nonexistent/step \
  -H "X-User-ID: patient-1"
# 404
```

```json
{"detail": "Resource not found"}
```

**Fix:** Create the session first with `POST /api/v1/sessions`.

### Duplicate Session

```bash
# Create the same session twice
curl -X POST http://localhost:8080/api/v1/sessions \
  -H "Content-Type: application/json" \
  -H "X-User-ID: patient-1" \
  -d '{"session_id": "sess-001"}'
# 409
```

```json
{"detail": "Resource already exists"}
```

**Fix:** Use a different `session_id`, or retrieve the existing session with `GET /api/v1/sessions/sess-001`.

### Wrong Pipeline Stage

```bash
# Try to submit a step answer when the pipeline is in llm_questioning stage
curl -X POST http://localhost:8080/api/v1/sessions/sess-001/step \
  -H "Content-Type: application/json" \
  -H "X-User-ID: patient-1" \
  -d '{"value": "some_answer"}'
# 400
```

```json
{"detail": "Invalid request"}
```

**Fix:** Check the step's `type` field. If it's `"llm_questions"`, use `POST /api/v1/sessions/{id}/llm-answers` instead.

!!! note "Sanitized error messages"
    Error responses return generic descriptions (`"Resource not found"`, `"Resource already exists"`, `"Invalid request"`) instead of exposing internal details like user IDs, session IDs, or pipeline stage names.  Full error details are logged server-side for debugging.

### Invalid Request Body (422)

FastAPI returns 422 when the request body doesn't match the expected schema:

```json
{
  "detail": [
    {
      "type": "missing",
      "loc": ["body", "session_id"],
      "msg": "Field required",
      "input": {}
    }
  ]
}
```

**Fix:** Check the [API Reference](api-reference.md) for the expected request body format, or use the [Swagger UI](/docs) to explore endpoint schemas interactively.

## Error Handling in Client Code

=== "Python"

    ```python
    import httpx

    client = httpx.Client(base_url="http://localhost:8080")
    headers = {"X-User-ID": "patient-1"}

    resp = client.post(
        "/api/v1/sessions",
        json={"session_id": "sess-001"},
        headers=headers,
    )

    if resp.status_code == 201:
        session = resp.json()
    elif resp.status_code == 409:
        print("Session already exists, fetching it instead")
        resp = client.get("/api/v1/sessions/sess-001", headers=headers)
        session = resp.json()
    else:
        print(f"Error {resp.status_code}: {resp.json()['detail']}")
    ```

=== "JavaScript"

    ```javascript
    const resp = await fetch("http://localhost:8080/api/v1/sessions", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-User-ID": "patient-1",
      },
      body: JSON.stringify({ session_id: "sess-001" }),
    });

    if (resp.status === 201) {
      const session = await resp.json();
    } else if (resp.status === 409) {
      console.log("Session already exists");
    } else {
      const error = await resp.json();
      console.error(`Error ${resp.status}: ${error.detail}`);
    }
    ```
