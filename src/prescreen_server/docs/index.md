# Prescreen API Server

REST API for the ThaiLLM prescreening pipeline. This server exposes the rule-based prescreening SDK over HTTP, enabling client applications to drive patients through a structured triage flow.

## What It Does

The prescreening system achieves three goals:

1. **Department routing** — redirect the patient to the appropriate hospital department
2. **Differential diagnosis (DDx)** — narrow down possible diseases
3. **Severity assessment** — triage into one of 4 levels:
    - Observe at Home
    - Visit Hospital / Clinic
    - Visit Hospital / Clinic Urgently
    - Emergency

## How It Works

A prescreening session progresses through **6 phases** of rule-based questions, optionally followed by LLM-generated follow-up questions and a prediction stage. The API manages the session state, serves one step at a time, and returns a final result with department, severity, and diagnosis information.

```
Client                          API Server
  │                                │
  ├─ POST /api/v1/sessions ──────►│  Create session
  │◄──────────────── 201 ─────────┤
  │                                │
  ├─ GET  /sessions/{id}/step ───►│  Get current step (questions)
  │◄──────────── questions ───────┤
  │                                │
  ├─ POST /sessions/{id}/step ───►│  Submit answers
  │◄──────── next questions ──────┤
  │                                │
  │       ... repeat ...           │
  │                                │
  │◄──── pipeline_result ─────────┤  Final result (dept + severity + DDx)
```

## Quick Links

| Resource | URL |
|----------|-----|
| **This Guide** | [`/guide/`](/guide/) |
| **Swagger UI** (interactive) | [`/docs`](/docs) |
| **ReDoc** (readable) | [`/redoc`](/redoc) |
| **Health Check** | [`/health`](/health) |

## Next Steps

- [Getting Started](getting-started.md) — install, run, and make your first request
- [Flow Walkthrough](flow-walkthrough.md) — understand the 6-phase prescreening flow
- [API Reference](api-reference.md) — endpoint table and model shapes
