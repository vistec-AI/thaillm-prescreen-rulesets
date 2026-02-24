# API Reference

The interactive API documentation is available at:

- **Swagger UI** — [`/docs`](/docs) (try requests directly in the browser)
- **ReDoc** — [`/redoc`](/redoc) (clean, readable format)

This page provides a quick-reference endpoint table and key model shapes.

## Endpoints

### Health

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/health` | No | Database connectivity check. Returns `{"status": "ok"}` or `{"status": "error", "detail": "..."}`. |

### Sessions

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/api/v1/sessions` | `X-User-ID` | Create a new prescreening session. Body: `{"session_id": "...", "ruleset_version": "..."}`. Returns 201. |
| `GET` | `/api/v1/sessions/{session_id}` | `X-User-ID` | Get session info. Returns 404 if not found. |
| `GET` | `/api/v1/sessions` | `X-User-ID` | List sessions for the current user. Query params: `limit` (1–`MAX_PAGE_LIMIT`, default `DEFAULT_PAGE_LIMIT`), `offset` (default 0). See [Environment Variables](environment-variables.md#pagination). |
| `DELETE` | `/api/v1/sessions/{session_id}` | `X-User-ID` | Soft-delete a session. The row is retained but hidden from queries. Returns 204. |
| `DELETE` | `/api/v1/sessions/{session_id}/permanent` | `X-User-ID` | Permanently delete a session (irreversible, for GDPR erasure). Returns 204. |

### Steps

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/api/v1/sessions/{session_id}/step` | `X-User-ID` | Get the current step. Response type depends on pipeline stage. |
| `POST` | `/api/v1/sessions/{session_id}/step` | `X-User-ID` | Submit an answer. Body: `{"qid": "...", "value": ...}`. `qid` is optional. |
| `POST` | `/api/v1/sessions/{session_id}/back-edit` | `X-User-ID` | Revert to a previous phase or question. Body: `{"target_phase": N, "target_qid": "..."}`. `target_qid` optional, only for phases 4-5. |
| `POST` | `/api/v1/sessions/{session_id}/step-back` | `X-User-ID` | Go back one step automatically. No request body needed — the engine determines the previous step. Returns 400 if already at phase 0. |

### LLM

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/api/v1/sessions/{session_id}/llm-answers` | `X-User-ID` | Submit LLM follow-up answers. Body: list of `{"question": "...", "answer": "..."}`. |
| `GET` | `/api/v1/sessions/{session_id}/llm-prompt` | `X-User-ID` | Get the current step rendered as an LLM-ready prompt string. |

### Reference Data

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/api/v1/reference/departments` | No | List all hospital departments. |
| `GET` | `/api/v1/reference/severity-levels` | No | List all severity/triage levels. |
| `GET` | `/api/v1/reference/symptoms` | No | List all NHSO symptoms. |
| `GET` | `/api/v1/reference/underlying-diseases` | No | List all underlying diseases. |

### Admin (Bulk Cleanup)

These endpoints require the `X-Admin-Key` header matching the `ADMIN_API_KEY` environment variable. Returns 401 if the header is missing, 403 if the key is invalid or not configured.

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/api/v1/admin/cleanup/sessions` | `X-Admin-Key` | Bulk soft-delete or hard-delete old sessions. Query params: `older_than_days` (default `DEFAULT_CLEANUP_DAYS`), `status` (repeatable filter), `hard` (default false). See [Environment Variables](environment-variables.md#session-cleanup). |
| `POST` | `/api/v1/admin/cleanup/purge-deleted` | `X-Admin-Key` | Permanently remove soft-deleted rows. Query params: `older_than_days` (default 0 = all). |

## Key Response Shapes

### SessionInfo

Returned by session creation and retrieval endpoints.

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

### QuestionsStep

Returned when `type` is `"questions"` — the client should render these and collect answers.

```json
{
  "type": "questions",
  "phase": 0,
  "phase_name": "Demographics",
  "questions": [
    {
      "qid": "demo_dob",
      "question": "Date of birth",
      "question_type": "datetime",
      "answer_schema": {"type": "string", "format": "date"}
    }
  ],
  "submission_schema": {
    "type": "object",
    "properties": {"demo_dob": {"type": "string", "format": "date"}},
    "required": ["demo_dob"]
  }
}
```

### LLMQuestionsStep

Returned when `type` is `"llm_questions"` — LLM-generated follow-up questions.

```json
{
  "type": "llm_questions",
  "questions": [
    "Does the headache get worse when you bend forward?",
    "Have you experienced any visual disturbances?"
  ]
}
```

### PipelineResult

Returned when `type` is `"pipeline_result"` — the final outcome.

```json
{
  "type": "pipeline_result",
  "departments": [
    {"id": "dept004", "name": "Internal Medicine", "name_th": "อายุรกรรม", "description": "..."}
  ],
  "severity": {
    "id": "sev002",
    "name": "Visit Hospital / Clinic",
    "name_th": "เข้าพบโรงพยาบาลหรือคลินิกเมื่อสะดวกเพื่อตรวจสอบอาการเพิ่ม",
    "description": "..."
  },
  "diagnoses": [
    {"disease_id": "d042", "confidence": 0.82}
  ],
  "reason": "OPD routing: hea_opd_005 → dept004",
  "terminated_early": false
}
```

### CleanupResult

Returned by admin cleanup endpoints.

```json
{
  "affected_rows": 42,
  "action": "soft_delete"
}
```

The `action` field is one of `"soft_delete"`, `"hard_delete"`, or `"purge_soft_deleted"`.

### BackEditRequest

Body for `POST /sessions/{session_id}/back-edit`.

```json
{
  "target_phase": 1,
  "target_qid": null
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `target_phase` | `int` | Yes | Phase to revert to (0-5). Must be less than current phase, or equal for intra-phase back-edit in phases 4-5. |
| `target_qid` | `string \| null` | No | For phases 4-5 only: jump to a specific previously-answered question within the phase. |

The response is a `QuestionsStep` at the reverted position. For bulk phases (0-3), question metadata includes `previous_value` with the patient's earlier answer to help UIs pre-fill forms.

### Error Response

All error responses follow the same shape:

```json
{
  "detail": "Human-readable error message"
}
```

## Reference Data Response Shapes

### Departments

`GET /api/v1/reference/departments`

```json
[
  {
    "id": "dept001",
    "name": "Dermatology",
    "name_th": "แผนกผิวหนัง",
    "description": "Deals with diseases and conditions of the skin, hair, and nails."
  },
  {
    "id": "dept002",
    "name": "Emergency Medicine",
    "name_th": "แผนกฉุกเฉิน",
    "description": "Focuses on the immediate diagnosis and treatment of acute and life-threatening illnesses..."
  },
  {
    "id": "dept004",
    "name": "Internal Medicine",
    "name_th": "อายุรกรรม",
    "description": "Specializes in the prevention, diagnosis, and treatment of diseases affecting adults..."
  }
]
```

Full list: `dept001`–`dept012` (12 departments). See the [Flow Walkthrough — Departments](flow-walkthrough.md#departments) for the complete table.

### Severity Levels

`GET /api/v1/reference/severity-levels`

```json
[
  {"id": "sev001", "name": "Observe at Home", "name_th": "เฝ้าสังเกตอาการที่บ้าน", "description": "..."},
  {"id": "sev002", "name": "Visit Hospital / Clinic", "name_th": "เข้าพบโรงพยาบาลหรือคลินิก...", "description": "..."},
  {"id": "sev002_5", "name": "Visit Hospital / Clinic Urgently", "name_th": "แนะนำให้เข้าพบโรงพยาบาลภายใน 24 ชั่วโมง...", "description": "..."},
  {"id": "sev003", "name": "Emergency", "name_th": "ฉุกเฉิน", "description": "..."}
]
```

### Symptoms

`GET /api/v1/reference/symptoms`

```json
[
  {"name": "Headache", "name_th": "ปวดหัว"},
  {"name": "Dizziness", "name_th": "เวียนหัว"},
  {"name": "Pain in Joint", "name_th": "ปวดข้อ"},
  {"name": "Muscle Pain", "name_th": "เจ็บกล้ามเนื้อ"},
  {"name": "Fever", "name_th": "ไข้"},
  {"name": "Cough", "name_th": "ไอ"},
  {"name": "Sore Throat", "name_th": "เจ็บคอ"},
  {"name": "Stomachache", "name_th": "ปวดท้อง"},
  {"name": "Constipation", "name_th": "ท้องผูก"},
  {"name": "Diarrhea", "name_th": "ท้องเสีย"},
  {"name": "Dysuria", "name_th": "ถ่ายปัสสาวะขัด"},
  {"name": "Vaginal Discharge", "name_th": "ตกขาวผิดปกติ"},
  {"name": "Skin Rash/Lesion", "name_th": "อาการทางผิวหนัง ผื่น คัน"},
  {"name": "Wound", "name_th": "บาดแผล"},
  {"name": "Eye Disorder", "name_th": "ความผิดปกติต่างๆที่เกิดขึ้นกับตา"},
  {"name": "Ear Disorder", "name_th": "ความผิดปกติต่างๆ ที่เกิดขึ้นกับหู"}
]
```

Use the `name` field as the value when submitting `primary_symptom` or `secondary_symptoms` in Phase 2.

### Underlying Diseases

`GET /api/v1/reference/underlying-diseases`

```json
[
  {"name": "Hypertension", "name_th": "ความดันโลหิตสูง"},
  {"name": "Dyslipidemia", "name_th": "ไขมันในเลือดผิดปกติ"},
  {"name": "Diabetes Mellitus", "name_th": "เบาหวาน"},
  {"name": "Chronic kidney disease", "name_th": "โรคไตเรื้อรัง"},
  {"name": "Chronic liver disease", "name_th": "โรคตับเรื้อรัง"},
  {"name": "Heart disease", "name_th": "โรคหัวใจ"},
  {"name": "Thyroid disease", "name_th": "ความผิดปกติของต่อมไทรอยด์"},
  {"name": "Stroke", "name_th": "โรคหลอดเลือดสมอง"},
  {"name": "Obesity", "name_th": "โรคอ้วน"},
  {"name": "Chronic Obstructive Pulmonary Disease", "name_th": "โรคปอดอุดกั้นเรื้อรัง"},
  {"name": "Asthma", "name_th": "โรคหอบหืด"},
  {"name": "Tuberculosis", "name_th": "วัณโรค"},
  {"name": "HIV/AIDS", "name_th": "เอดส์"},
  {"name": "Cancer", "name_th": "มะเร็ง"},
  {"name": "Allergy", "name_th": "โรคภูมิแพ้"},
  {"name": "Alzheimer disease", "name_th": "โรคอัลไซเมอร์"}
]
```

Use the `name` field as values in the `underlying_diseases` list when submitting demographics (Phase 0).

## Answer Format by Question Type

| Question Type | Value Type | Example |
|---------------|-----------|---------|
| `single_select` | String (option ID) | `"เคย"` |
| `multi_select` | List of strings | `["ตุบ", "แน่นๆ"]` |
| `free_text` | String | `"3 วันก่อน"` |
| `free_text_with_fields` | Object | `{"field_id": "value"}` |
| `number_range` | Number | `5` |
| `image_single_select` | String (option ID) | `"stomach_2"` |
| `image_multi_select` | List of strings | `["stomach_2", "stomach_5"]` |

See the [Flow Walkthrough — OLDCARTS](flow-walkthrough.md#phase-4-oldcarts-sequential) for detailed examples of each question type with full request/response payloads.
