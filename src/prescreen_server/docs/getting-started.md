# Getting Started

## Prerequisites

- **Python 3.13+**
- **uv** — Python package manager ([install guide](https://docs.astral.sh/uv/getting-started/installation/))
- **PostgreSQL** — for session persistence (or use the Docker Compose setup)

## Installation

### Local Development

```bash
# Clone the repository
git clone <repo-url>
cd thaillm-prescreen-rulesets

# Install dependencies
uv pip install -e .

# Set up the database (requires a running PostgreSQL instance)
export PG_HOST=localhost PG_PORT=5432 PG_USER=prescreen PG_PASSWORD=prescreen PG_DATABASE=prescreen

# Run database migrations
cd src/prescreen_db && uv run alembic upgrade head && cd ../..

# Start the server
uv run prescreen-server
```

The server starts at `http://localhost:8080`.

### Docker (Full Stack)

```bash
docker compose up --build
```

This starts both the API server and PostgreSQL. The server is available at `http://localhost:8080`.

## Verify the Server Is Running

```bash
curl http://localhost:8080/health
```

Expected response:

```json
{"status": "ok"}
```

## Your First Prescreening Session

Here's a minimal walkthrough: create a session, get the first step, and submit demographics.

### 1. Create a Session

=== "curl"

    ```bash
    curl -X POST http://localhost:8080/api/v1/sessions \
      -H "Content-Type: application/json" \
      -H "X-User-ID: patient-1" \
      -d '{"session_id": "sess-001"}'
    ```

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
    session = resp.json()
    print(session)
    ```

Response (201):

```json
{
  "session_id": "sess-001",
  "user_id": "patient-1",
  "phase": 0,
  "phase_name": "Demographics",
  "pipeline_stage": "rule_based",
  "status": "in_progress"
}
```

### 2. Get the Current Step

=== "curl"

    ```bash
    curl http://localhost:8080/api/v1/sessions/sess-001/step \
      -H "X-User-ID: patient-1"
    ```

=== "Python"

    ```python
    resp = client.get(
        "/api/v1/sessions/sess-001/step",
        headers=headers,
    )
    step = resp.json()
    print(step["type"])       # "questions"
    print(step["phase_name"]) # "Demographics"
    ```

The response is a `QuestionsStep` with `type: "questions"` and a list of demographic fields to collect.

### 3. Submit Demographics

The demographics payload includes fields with fixed enum values:

- **`gender`**: `"Male"` or `"Female"`
- **`underlying_diseases`**: list of disease names (e.g. `"Hypertension"`, `"Diabetes Mellitus"`) or `[]` for none

See the [Flow Walkthrough — Reference Data](flow-walkthrough.md#reference-data-enums-fixed-values) for the full list of accepted values.

=== "curl"

    ```bash
    curl -X POST http://localhost:8080/api/v1/sessions/sess-001/step \
      -H "Content-Type: application/json" \
      -H "X-User-ID: patient-1" \
      -d '{
        "value": {
          "date_of_birth": "1990-01-15",
          "gender": "Male",
          "height": 175,
          "weight": 70,
          "underlying_diseases": ["Hypertension"],
          "medical_history": "None",
          "occupation": "Engineer",
          "presenting_complaint": "Headache for 3 days"
        }
      }'
    ```

=== "Python"

    ```python
    resp = client.post(
        "/api/v1/sessions/sess-001/step",
        json={
            "value": {
                "date_of_birth": "1990-01-15",
                "gender": "Male",
                "height": 175,
                "weight": 70,
                "underlying_diseases": ["Hypertension"],
                "medical_history": "None",
                "occupation": "Engineer",
                "presenting_complaint": "Headache for 3 days",
            }
        },
        headers=headers,
    )
    next_step = resp.json()
    print(next_step["phase_name"])  # "ER Critical Screen"
    ```

The response is the next step — Phase 1 (ER Critical Screen) with 11 yes/no questions.

### 4. Continue the Flow

Keep calling `GET /step` and `POST /step` for each phase until you receive a response with `type: "pipeline_result"`, which contains the final department routing, severity assessment, and diagnosis.

See the [Flow Walkthrough](flow-walkthrough.md) for a complete phase-by-phase guide.
