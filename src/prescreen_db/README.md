# prescreen_db

PostgreSQL persistence layer for prescreen sessions.

## Database Diagram

### Table: `prescreen_sessions`

```
┌──────────────────────────────────────────────────────────────────────┐
│                        prescreen_sessions                            │
├──────────────────────┬───────────────┬───────────────────────────────┤
│ Column               │ Type          │ Notes                         │
├──────────────────────┼───────────────┼───────────────────────────────┤
│ id                   │ UUID          │ PK, default uuid4             │
│ user_id              │ TEXT          │ NOT NULL, indexed             │
│ session_id           │ TEXT          │ NOT NULL                      │
│ status               │ VARCHAR(20)   │ NOT NULL, default 'created'   │
│ current_phase        │ SMALLINT      │ NOT NULL, default 0           │
│ ruleset_version      │ TEXT          │ nullable                      │
│ demographics         │ JSONB         │ NOT NULL, default '{}'        │
│ primary_symptom      │ TEXT          │ nullable                      │
│ secondary_symptoms   │ TEXT[]        │ nullable                      │
│ responses            │ JSONB         │ NOT NULL, default '{}'        │
│ er_flags             │ JSONB         │ nullable                      │
│ terminated_at_phase  │ SMALLINT      │ nullable                      │
│ termination_reason   │ TEXT          │ nullable                      │
│ result               │ JSONB         │ nullable                      │
│ created_at           │ TIMESTAMPTZ   │ NOT NULL, auto                │
│ updated_at           │ TIMESTAMPTZ   │ NOT NULL, auto on update      │
│ completed_at         │ TIMESTAMPTZ   │ nullable                      │
└──────────────────────┴───────────────┴───────────────────────────────┘
```

### Column ↔ Phase Mapping

Each column group maps to a specific phase in the prescreening flow:

```
Phase 0 ─ Demographics  ──────────► demographics (JSONB)
Phase 1 ─ Triage questions ───────► responses (JSONB, keyed by qid)
Phase 2 ─ Symptom selection ──────► primary_symptom, secondary_symptoms
Phase 3 ─ ER checklist ──────────► responses (JSONB) + er_flags (JSONB)
Phase 4 ─ OPD deep-dive ─────────► responses (JSONB, keyed by qid)
Phase 5 ─ Result ────────────────► result (JSONB)
```

### Session Status Lifecycle

```
                 ┌───────────┐
                 │  created  │
                 └─────┬─────┘
                       │  first answer
                       ▼
               ┌───────────────┐
               │  in_progress  │
               └───┬───────┬───┘
      all phases   │       │  early exit (e.g. ER)
      completed    │       │
                   ▼       ▼
           ┌───────────┐ ┌────────────┐
           │ completed │ │ terminated │
           └───────────┘ └────────────┘
```

### Constraints

| Name                    | Type   | Rule                                                       |
|-------------------------|--------|------------------------------------------------------------|
| `uq_user_session`       | UNIQUE | `(user_id, session_id)` — one session per id per user      |
| `ck_phase_range`        | CHECK  | `current_phase BETWEEN 0 AND 5`                            |
| `ck_completed_has_result`| CHECK | `status != 'completed' OR result IS NOT NULL`              |
| `ck_terminated_has_phase`| CHECK | `status != 'terminated' OR terminated_at_phase IS NOT NULL`|

### Indexes

| Name                    | Type              | Columns / Expression                              |
|-------------------------|-------------------|----------------------------------------------------|
| `ix_prescreen_sessions_user_id` | B-tree   | `user_id`                                          |
| `ix_prescreen_sessions_status`  | B-tree   | `status`                                           |
| `ix_primary_symptom`    | B-tree (partial)  | `primary_symptom WHERE primary_symptom IS NOT NULL` |
| `ix_responses_gin`      | GIN               | `responses`                                         |
| `ix_demographics_gin`   | GIN               | `demographics`                                      |
| `ix_result_gin`         | GIN (partial)     | `result WHERE result IS NOT NULL`                   |
| `ix_active_user_session`| B-tree (partial)  | `(user_id, session_id) WHERE status IN ('created','in_progress')` |

### JSONB Column Shapes

```jsonc
// demographics — Phase 0 flat dict
{
  "dob": "1990-01-15",
  "gender": "male",
  "height": 175,
  "weight": 70
}

// responses — Phase 1/3/4 answers keyed by question ID
{
  "triage_q1_fever": {
    "value": "yes",
    "answered_at": "2025-02-20T10:30:00+00:00"
  },
  "opd_ortho_q2_pain_level": {
    "value": 7,
    "answered_at": "2025-02-20T10:32:00+00:00"
  }
}

// er_flags — Phase 3 ER checklist items answered "yes"
{
  "chest_pain": true,
  "difficulty_breathing": true
}

// result — Phase 5 final routing output
{
  "departments": ["orthopedics"],
  "severity": "visit_hospital_urgently",
  "ddx": ["fracture", "sprain"]
}
```
