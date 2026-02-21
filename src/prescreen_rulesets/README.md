# prescreen_rulesets SDK

Rule-based prescreening SDK that drives patients through a 6-phase triage flow.
Loads decision-tree rulesets from YAML, manages session state via a database,
and returns typed step results that API consumers can render directly.

## Installation

```bash
uv pip install -e .
```

Requires Python 3.13+ and a PostgreSQL database (for session persistence via `prescreen_db`).

## Quick Start

```python
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from prescreen_rulesets import PrescreenEngine, RulesetStore

# 1. Load rulesets once at startup
store = RulesetStore()        # defaults to v1/ relative to repo root
store.load()

# 2. Create the engine
engine = PrescreenEngine(store)

# 3. Set up your async DB session
db_engine = create_async_engine("postgresql+asyncpg://user:pass@localhost/prescreen")
Session = async_sessionmaker(db_engine)

# 4. Run a prescreening session
async with Session() as db:
    # Create a new session
    info = await engine.create_session(db, user_id="patient-1", session_id="sess-1")

    # See what to show the user
    step = await engine.get_current_step(db, user_id="patient-1", session_id="sess-1")

    # Submit an answer and get the next step
    step = await engine.submit_answer(
        db, user_id="patient-1", session_id="sess-1",
        qid="demographics",
        value={"gender": "Male", "age": 35, "height": 175, "weight": 70},
    )

    await db.commit()
```

## Core Concepts

### The 6-Phase Flow

Every prescreening session progresses through these phases:

| Phase | Name | Mode | What happens |
|-------|------|------|--------------|
| 0 | Demographics | bulk | Collect date of birth, gender, height, weight, etc. |
| 1 | ER Critical Screen | bulk | 11 yes/no life-threatening checks. Any "yes" terminates immediately (Emergency). |
| 2 | Symptom Selection | bulk | Patient picks a primary symptom (+ optional secondary) from 16 NHSO symptoms. |
| 3 | ER Checklist | bulk | Age-appropriate checklist for selected symptoms. First positive terminates. |
| 4 | OLDCARTS | sequential | Symptom-specific decision tree (Onset, Location, Duration, Character, etc.). |
| 5 | OPD | sequential | Conditional routing tree that determines the final department and severity. |

**Bulk phases (0-3):** All questions are presented at once. Submit all answers in a single call.

**Sequential phases (4-5):** Questions are presented one at a time. The engine automatically resolves filter/conditional questions behind the scenes and only surfaces user-facing questions.

### StepResult

Every engine method returns a `StepResult`, which is one of:

**`QuestionsStep`** — present questions to the user:
```python
{
    "type": "questions",
    "phase": 0,
    "phase_name": "Demographics",
    "questions": [
        {"qid": "demo_dob", "question": "...", "question_type": "datetime", ...},
        {"qid": "demo_gender", "question": "...", "question_type": "enum", "options": [...]},
        ...
    ]
}
```

**`TerminationStep`** — session ended with a result:
```python
{
    "type": "terminated",       # or "completed"
    "phase": 1,
    "departments": [{"id": "dept002", "name": "Emergency Medicine", ...}],
    "severity": {"id": "sev003", "name": "Emergency", ...},
    "reason": "ER critical positive: emer_critical_001"
}
```

Dispatch on `step.type` to decide what to render.

### Schema Fields

Each `QuestionPayload` carries an optional `answer_schema` — a JSON-Schema-like dict describing the expected answer format. Each `QuestionsStep` carries an optional `submission_schema` — the shape of the `value` parameter to `submit_answer()`.

**Question type → `answer_schema` mapping:**

| Question type | Schema |
|---------------|--------|
| `single_select` / `image_single_select` | `{"type": "string", "enum": [option_ids]}` |
| `multi_select` / `image_multi_select` | `{"type": "array", "items": {"type": "string", "enum": [...]}}` |
| `number_range` | `{"type": "number", "minimum": N, "maximum": N}` |
| `free_text` | `{"type": "string"}` |
| `free_text_with_fields` | `{"type": "object", "properties": {...}, "required": [...]}` |
| `datetime` (demographics) | `{"type": "string", "format": "date"}` |
| `enum` (demographics) | `{"type": "string", "enum": [values]}` |
| `float` (demographics) | `{"type": "number"}` |
| `yes_no` (ER critical/checklist) | `{"type": "boolean"}` |

**Phase → `submission_schema` shape:**

| Phase | submission_schema type |
|-------|-----------------------|
| 0 (Demographics) | `{"type": "object", "properties": {key: schema}, "required": [...]}` |
| 1 (ER Critical) | `{"type": "object", "properties": {qid: {"type": "boolean"}}, "required": [...]}` |
| 2 (Symptom Selection) | `{"type": "object", "properties": {"primary_symptom": ..., "secondary_symptoms": ...}, "required": ["primary_symptom"]}` |
| 3 (ER Checklist) | `{"type": "object", "properties": {qid: {"type": "boolean"}}, "required": [...]}` |
| 4-5 (Sequential) | Same as the single question's `answer_schema` |

### LLM Prompt Rendering

`PromptManager` renders `QuestionsStep` objects into LLM-ready prompt strings with JSON response format instructions. It uses Jinja2 templates and dispatches by phase (bulk) or question type (sequential).

```python
from prescreen_rulesets import PromptManager

pm = PromptManager()
prompt = pm.render_step(step)  # step is a QuestionsStep
# Returns a string like:
# "Phase 0 — Demographics\n\nPlease provide the following..."
```

The pipeline also provides a convenience method that handles both stages:

```python
prompt = await pipeline.get_llm_prompt(
    db, user_id="patient-1", session_id="sess-1",
)
# During rule_based stage: renders the current engine step
# During llm_questioning stage: renders LLM follow-up questions as free-text prompts
# Returns None when pipeline_stage is "done" or session is terminated
```

## API Reference

### `PrescreenEngine`

The main orchestrator. Stateless — all state is read from and written to the database on every call.

```python
engine = PrescreenEngine(store)
```

#### Session Lifecycle

```python
# Create a new session (starts at phase 0)
info: SessionInfo = await engine.create_session(
    db, user_id="u1", session_id="s1",
    ruleset_version="v1",           # optional tag for traceability
)

# Fetch session info
info: SessionInfo | None = await engine.get_session(
    db, user_id="u1", session_id="s1",
)

# List sessions for a user (most recent first)
sessions: list[SessionInfo] = await engine.list_sessions(
    db, user_id="u1", limit=20, offset=0,
)
```

#### Step API

```python
# Read-only: see what to show the user right now
step: StepResult = await engine.get_current_step(
    db, user_id="u1", session_id="s1",
)

# Submit an answer and advance the session
step: StepResult = await engine.submit_answer(
    db, user_id="u1", session_id="s1",
    qid="demographics",    # optional: phase marker (bulk) or question ID (sequential)
    value={...},            # full batch (bulk) or single answer (sequential)
)

# qid is optional — for bulk phases (0-3) it is ignored, and for sequential
# phases (4-5) it is auto-derived from the current step when omitted:
step: StepResult = await engine.submit_answer(
    db, user_id="u1", session_id="s1",
    value={...},            # qid omitted — engine derives it automatically
)
```

#### Submitting Answers Per Phase

The `qid` parameter is **optional** in `submit_answer()`.  For bulk phases
(0-3) it is ignored by the engine, and for sequential phases (4-5) it is
auto-derived from the current step when omitted.  You can still pass it
explicitly for clarity or backward compatibility.

Each phase expects a different `value` shape:

**Phase 0 — Demographics:**
```python
await engine.submit_answer(db, user_id=..., session_id=...,
    qid="demographics",
    value={
        "date_of_birth": "1990-01-15",
        "gender": "Male",
        "height": 175,
        "weight": 70,
        "underlying_diseases": ["Hypertension"],
        "medical_history": "None",
        "occupation": "Engineer",
        "presenting_complaint": "Headache for 3 days",
    },
)
```

**Phase 1 — ER Critical Screen:**
```python
await engine.submit_answer(db, user_id=..., session_id=...,
    qid="er_critical",
    value={
        "emer_critical_001": False,
        "emer_critical_002": False,
        # ... all 11 items, True = yes
    },
)
```

**Phase 2 — Symptom Selection:**
```python
await engine.submit_answer(db, user_id=..., session_id=...,
    qid="symptoms",
    value={
        "primary_symptom": "Headache",
        "secondary_symptoms": ["Dizziness"],  # optional
    },
)
```

**Phase 3 — ER Checklist:**
```python
await engine.submit_answer(db, user_id=..., session_id=...,
    qid="er_checklist",
    value={
        "emer_adult_hea1": False,
        "emer_adult_hea2": False,
        # ... all checklist items for selected symptoms
    },
)
```

**Phases 4-5 — Sequential (OLDCARTS / OPD):**
```python
# qid can be omitted — the engine auto-derives it from the current step
await engine.submit_answer(db, user_id=..., session_id=...,
    value="sudden_onset",       # single_select: option ID
)

# Or pass qid explicitly if preferred
await engine.submit_answer(db, user_id=..., session_id=...,
    qid="hea_o_001",           # the question's qid
    value="sudden_onset",       # single_select: option ID
)

# Other answer shapes by question type:
#   free_text:              "patient's text"
#   free_text_with_fields:  {"field_id": "value", ...}
#   number_range:           7.5
#   single_select:          "option_id"
#   multi_select:           ["opt1", "opt2"]
#   image_single_select:    "option_id"
#   image_multi_select:     ["opt1", "opt2"]
```

### `RulesetStore`

Loads all YAML rulesets from `v1/` into typed Pydantic models. Load once at startup and share across requests.

```python
store = RulesetStore()          # auto-discovers v1/ from repo root
store = RulesetStore("/path/to/v1")  # or provide an explicit path
store.load()
```

#### Reference Data

```python
store.departments         # dict[str, DepartmentConst]  — 12 departments
store.severity_levels     # dict[str, SeverityConst]    — 4 severity levels
store.nhso_symptoms       # dict[str, NHSOSymptom]      — 16 NHSO symptoms
store.underlying_diseases # list[UnderlyingDisease]
store.demographics        # list[DemographicField]      — 8 fields
store.er_critical         # list[ERCriticalItem]         — 11 critical checks
```

#### Decision Tree Lookups

```python
# Get the first question ID for a symptom tree
qid = store.get_first_qid("oldcarts", "Headache")   # e.g. "hea_o_001"
qid = store.get_first_qid("opd", "Headache")        # e.g. "hea_opd_001"

# Get a single question by source, symptom, and qid
question = store.get_question("oldcarts", "Headache", "hea_o_001")

# Get all questions for a symptom
questions = store.get_questions_for_symptom("opd", "Headache")
# Returns dict[str, Question] in YAML order
```

#### ER Checklists

```python
# Adult checklist (age >= 15)
items = store.get_er_checklist("Headache", pediatric=False)

# Pediatric checklist (age < 15)
items = store.get_er_checklist("Headache", pediatric=True)
```

#### Resolving IDs to Display Data

```python
store.resolve_department("dept002")
# {"id": "dept002", "name": "Emergency Medicine",
#  "name_th": "แผนกฉุกเฉิน", "description": "..."}

store.resolve_severity("sev003")
# {"id": "sev003", "name": "Emergency",
#  "name_th": "ฉุกเฉิน", "description": "..."}
```

### `ConditionalEvaluator`

Resolves auto-evaluated question types (`gender_filter`, `age_filter`, `conditional`) without user input. Normally used internally by the engine, but available for standalone use.

```python
from prescreen_rulesets.evaluator import ConditionalEvaluator

evaluator = ConditionalEvaluator()
action = evaluator.evaluate(question, answers={"q1": "yes"}, demographics={"age": 30})
# Returns a GotoAction, OPDAction, TerminateAction, or None
```

#### Predicate Operators

Conditional questions use predicates to match prior answers. Supported operators:

| Operator | Description | Value type |
|----------|-------------|------------|
| `eq` | Equal | any |
| `ne` | Not equal | any |
| `lt` | Less than | numeric |
| `le` | Less than or equal | numeric |
| `gt` | Greater than | numeric |
| `ge` | Greater than or equal | numeric |
| `between` | Inclusive range | `[min, max]` |
| `contains` | Substring or list element | string or item |
| `not_contains` | Inverse of contains | string or item |
| `contains_any` | Any item present | list |
| `contains_all` | All items present | list |
| `matches` | Regex match | regex string |

## Transaction Control

The engine calls `flush()` but never `commit()`. The caller controls transaction boundaries:

```python
async with Session() as db:
    step = await engine.submit_answer(db, ...)
    # Changes are flushed but not committed yet.
    # Inspect `step`, do validation, etc.
    await db.commit()      # persist
    # or: await db.rollback()  # discard
```

This lets you compose multiple engine calls in a single transaction or roll back on application-level errors.

## Using RulesetStore Without a Database

`RulesetStore` has no database dependency. You can use it standalone to inspect rulesets, build tooling, or run simulations:

```python
from prescreen_rulesets.ruleset import RulesetStore
from prescreen_rulesets.evaluator import ConditionalEvaluator
from prescreen_rulesets.constants import AUTO_EVAL_TYPES

store = RulesetStore()
store.load()

evaluator = ConditionalEvaluator()

# Walk a decision tree manually
symptom = "Headache"
qid = store.get_first_qid("oldcarts", symptom)
question = store.get_question("oldcarts", symptom, qid)

print(f"First question: {question.question}")
print(f"Type: {question.question_type}")

if question.question_type in AUTO_EVAL_TYPES:
    action = evaluator.evaluate(question, answers={}, demographics={"age": 30, "gender": "male"})
    print(f"Auto-resolved to: {action}")
```

## Pipeline

`PrescreenPipeline` orchestrates the full prescreening flow: rule-based engine, optional LLM question generation, and optional prediction. It wraps `PrescreenEngine` and manages the macro-stage transitions via the `pipeline_stage` DB column.

```
rule_based ──► llm_questioning ──► done
            │                        ▲
            └──── (early exit) ──────┘
```

### Quick Start

```python
from prescreen_rulesets import (
    PrescreenEngine, PrescreenPipeline, RulesetStore, LLMAnswer,
)

store = RulesetStore()
store.load()
engine = PrescreenEngine(store)

# Plug in your LLM generator and prediction head (both optional)
pipeline = PrescreenPipeline(
    engine, store,
    generator=MyLLMQuestionGenerator(llm_client=...),
    predictor=MyPredictionHead(model=...),
)

async with Session() as db:
    # Create session (same API as engine)
    info = await pipeline.create_session(db, user_id="p1", session_id="s1")

    # Rule-based phase — pipeline proxies to engine
    step = await pipeline.get_current_step(db, user_id="p1", session_id="s1")
    step = await pipeline.submit_answer(
        db, user_id="p1", session_id="s1",
        qid="demographics", value={...},
    )
    # ... submit answers through all phases until engine signals completion ...

    # If LLM questions are generated:
    #   step.type == "llm_questions"
    #   step.questions == ["Does the headache get worse when you bend forward?", ...]

    # Submit LLM answers
    result = await pipeline.submit_llm_answers(
        db, user_id="p1", session_id="s1",
        answers=[
            LLMAnswer(question="Does the headache get worse?", answer="Yes"),
        ],
    )
    # result.type == "pipeline_result"
    # result.departments, result.severity, result.diagnoses

    await db.commit()
```

### Pipeline API

```python
pipeline = PrescreenPipeline(engine, store, generator=..., predictor=...)
```

**`create_session(db, user_id, session_id)`** — Proxies to the engine. The `pipeline_stage` column defaults to `rule_based`.

**`get_current_step(db, user_id, session_id)`** → `PipelineStep` — Dispatches by `pipeline_stage`:
- `rule_based` → delegates to engine's `get_current_step`
- `llm_questioning` → returns `LLMQuestionsStep` with stored questions
- `done` → returns cached `PipelineResult`

**`submit_answer(db, user_id, session_id, qid=None, value=...)`** → `PipelineStep` — Only valid during `rule_based` stage. Delegates to the engine and handles the transition when the engine signals completion or termination. `qid` is optional — omit it for convenience (see engine docs).

**`submit_llm_answers(db, user_id, session_id, answers)`** → `PipelineResult` — Only valid during `llm_questioning` stage. Stores answers, runs prediction, and transitions to `done`.

### PipelineStep Types

`PipelineStep` is a union of step types the pipeline can return:

| Type | Class | When |
|------|-------|------|
| `"questions"` | `QuestionsStep` | During `rule_based` stage — present questions to the user |
| `"llm_questions"` | `LLMQuestionsStep` | Entering `llm_questioning` — LLM-generated follow-up questions |
| `"pipeline_result"` | `PipelineResult` | Stage is `done` — final result with DDx, departments, severity |

**`PipelineResult`** fields:
```python
{
    "type": "pipeline_result",
    "departments": [{"id": "dept004", "name": "Internal Medicine", ...}],
    "severity": {"id": "sev002", "name": "Visit Hospital / Clinic", ...},
    "diagnoses": [
        {"disease_id": "d042", "confidence": 0.82},
        {"disease_id": "d015", "confidence": 0.45},
    ],
    "reason": "...",              # termination reason if applicable
    "terminated_early": False,    # True if ER early exit
}
```

### Early Termination

If the rule-based engine terminates early (e.g. ER critical positive), the pipeline skips the LLM/prediction stages and returns a `PipelineResult` with `terminated_early=True` and an empty `diagnoses` list. The department and severity come from the rule-based engine.

### Without Generator or Predictor

Both `generator` and `predictor` are optional:
- **No generator:** skips the `llm_questioning` stage entirely; goes straight from rule-based completion to prediction (or `done`).
- **No predictor:** returns a `PipelineResult` with an empty `diagnoses` list; department and severity come from the rule-based engine alone.

## Post-Rule-Based Interfaces

The pipeline's optional stages (`QuestionGenerator` and `PredictionModule`) are defined as abstract base classes — concrete implementations live in separate packages.

```
Rule-based (phases 0-5)
        │
        ▼
  ┌─────────────────────┐     list[QAPair]       ┌───────────────────┐
  │  Collect rule-based  │ ──────────────────────▶│ QuestionGenerator │
  │  Q&A history         │                        │   (LLM follow-up) │
  └─────────────────────┘                        └────────┬──────────┘
                                                          │ GeneratedQuestions
                                                          ▼
                                                 Present to patient,
                                                 collect answers
                                                          │
        ┌─────────────────────────────────────────────────┘
        │  list[QAPair]  (rule-based + LLM pairs combined)
        ▼
  ┌──────────────────┐
  │ PredictionModule │ ──▶ PredictionResult
  │  (DDx + routing) │      • diagnoses: list[DiagnosisResult]
  └──────────────────┘      • departments: list[str]
                            • severity: str | None
```

### Data Models

**`QAPair`** — A single question-answer record. The `source` field distinguishes where it came from:

```python
from prescreen_rulesets import QAPair

# Rule-based pair (carries structured metadata)
rb_pair = QAPair(
    question="How did the headache start?",
    answer="sudden_onset",
    source="rule_based",
    qid="hea_o_001",
    question_type="single_select",
    phase=4,
)

# LLM-generated pair (free-form, no qid/phase)
llm_pair = QAPair(
    question="Does the headache get worse when you bend forward?",
    answer="Yes, significantly",
    source="llm_generated",
)
```

**`GeneratedQuestions`** — Wrapper returned by `QuestionGenerator`:

```python
from prescreen_rulesets import GeneratedQuestions

gen = GeneratedQuestions(questions=[
    "Does the headache get worse when you bend forward?",
    "Have you experienced any visual disturbances?",
])
```

**`PredictionResult`** / **`DiagnosisResult`** — Output of `PredictionModule`:

```python
from prescreen_rulesets import PredictionResult, DiagnosisResult

result = PredictionResult(
    diagnoses=[
        DiagnosisResult(disease_id="d042", confidence=0.82),
        DiagnosisResult(disease_id="d015", confidence=0.45),
    ],
    departments=["dept004"],     # Internal Medicine
    severity="sev002",           # Visit Hospital / Clinic
)
```

### Implementing `QuestionGenerator`

Subclass the ABC and implement the `generate` async method. The method receives the rule-based Q&A history and returns follow-up questions for the patient.

```python
from prescreen_rulesets import QuestionGenerator, QAPair, GeneratedQuestions


class MyLLMQuestionGenerator(QuestionGenerator):
    """Example implementation that calls an LLM to generate follow-up questions."""

    def __init__(self, llm_client):
        self.llm_client = llm_client

    async def generate(self, qa_pairs: list[QAPair]) -> GeneratedQuestions:
        # Build a prompt from the Q&A history
        history = "\n".join(
            f"Q: {p.question}\nA: {p.answer}" for p in qa_pairs
        )
        prompt = (
            "Based on this patient interview, generate 2-3 follow-up "
            "questions to narrow down the diagnosis:\n\n" + history
        )

        response = await self.llm_client.complete(prompt)

        # Parse the LLM output into individual question strings
        questions = [q.strip() for q in response.split("\n") if q.strip()]
        return GeneratedQuestions(questions=questions)
```

### Implementing `PredictionModule`

Subclass the ABC and implement the `predict` async method. The method receives all Q&A pairs (both rule-based and LLM-generated) and returns the diagnosis, department, and severity predictions.

```python
from prescreen_rulesets import (
    PredictionModule, QAPair, PredictionResult, DiagnosisResult,
)


class MyPredictionHead(PredictionModule):
    """Example implementation that runs a classifier on the Q&A pairs."""

    def __init__(self, model):
        self.model = model

    async def predict(self, qa_pairs: list[QAPair]) -> PredictionResult:
        # Separate sources if needed
        rb_pairs = [p for p in qa_pairs if p.source == "rule_based"]
        llm_pairs = [p for p in qa_pairs if p.source == "llm_generated"]

        # Feed into your model
        output = await self.model.infer(qa_pairs)

        return PredictionResult(
            diagnoses=[
                DiagnosisResult(disease_id=d["id"], confidence=d["score"])
                for d in output["diseases"]
            ],
            departments=output["departments"],   # e.g. ["dept004"]
            severity=output["severity"],         # e.g. "sev002"
        )
```

### End-to-End Integration

The recommended way to run the full flow is through `PrescreenPipeline`, which handles Q&A reconstruction, stage transitions, and result merging automatically:

```python
from prescreen_rulesets import (
    PrescreenEngine, PrescreenPipeline, RulesetStore, LLMAnswer,
)

store = RulesetStore()
store.load()
engine = PrescreenEngine(store)

pipeline = PrescreenPipeline(
    engine, store,
    generator=MyLLMQuestionGenerator(llm_client=...),
    predictor=MyPredictionHead(model=...),
)

async with Session() as db:
    await pipeline.create_session(db, user_id="p1", session_id="s1")

    # Submit answers through rule-based phases 0-5
    step = await pipeline.submit_answer(db, user_id="p1", session_id="s1",
                                         qid="demographics", value={...})
    # ... continue submitting answers ...

    # When engine finishes, pipeline auto-generates LLM questions:
    #   step.type == "llm_questions"

    # Collect patient answers and submit
    result = await pipeline.submit_llm_answers(
        db, user_id="p1", session_id="s1",
        answers=[LLMAnswer(question=q, answer=a) for q, a in patient_responses],
    )

    # result.type == "pipeline_result"
    print(result.diagnoses)     # ranked DDx list
    print(result.departments)   # resolved department dicts
    print(result.severity)      # resolved severity dict

    await db.commit()
```

If you need manual control (e.g. using the interfaces without the pipeline), you can call `QuestionGenerator` and `PredictionModule` directly:

```python
from prescreen_rulesets import QAPair

# Build QAPairs from your session's stored responses
rule_based_pairs: list[QAPair] = [...]

# LLM question generation
generator = MyLLMQuestionGenerator(llm_client=...)
generated = await generator.generate(rule_based_pairs)

# Present generated.questions to the patient, collect answers
llm_pairs = [
    QAPair(question=q, answer=a, source="llm_generated")
    for q, a in zip(generated.questions, patient_answers)
]

# Prediction
predictor = MyPredictionHead(model=...)
result = await predictor.predict(rule_based_pairs + llm_pairs)
```

### Reference Spaces

The prediction outputs are bounded by the constants in `v1/const/`:

| Output | Constant file | ID format | Example |
|--------|--------------|-----------|---------|
| `DiagnosisResult.disease_id` | `v1/const/diseases.yaml` | `d001`–`d###` | `d042` (Migraine) |
| `PredictionResult.departments` | `v1/const/departments.yaml` | `dept001`–`dept012` | `dept004` (Internal Medicine) |
| `PredictionResult.severity` | `v1/const/severity_levels.yaml` | `sev001`/`sev002`/`sev002_5`/`sev003` | `sev002` (Visit Hospital) |

## Package Layout

```
src/prescreen_rulesets/
├── __init__.py          # Public exports
├── engine.py            # PrescreenEngine — 6-phase rule-based orchestrator
├── pipeline.py          # PrescreenPipeline — full pipeline (engine + LLM + prediction)
├── ruleset.py           # RulesetStore — YAML loading + lookups
├── evaluator.py         # ConditionalEvaluator — auto-eval logic
├── constants.py         # Shared constants (severity order, phase names, defaults)
├── interfaces.py        # ABCs: QuestionGenerator, PredictionModule
└── models/
    ├── __init__.py      # Re-exports all model classes
    ├── action.py        # GotoAction, OPDAction, TerminateAction
    ├── question.py      # 10 question types + Question union + question_mapper
    ├── schema.py        # DepartmentConst, SeverityConst, NHSOSymptom, etc.
    ├── session.py       # StepResult, QuestionsStep, TerminationStep, SessionInfo
    └── pipeline.py      # QAPair, GeneratedQuestions, PredictionResult, DiagnosisResult,
                         # LLMAnswer, LLMQuestionsStep, PipelineResult, PipelineStep
```

## Testing

```bash
uv run pytest tests/test_ruleset_store.py -q     # RulesetStore smoke tests
uv run pytest tests/test_evaluator.py -q          # Evaluator unit tests
uv run pytest tests/test_tree_walkthrough.py -q   # Tree walkthrough (all symptoms)
uv run pytest tests/test_engine.py -q             # Engine with mocked DB
uv run pytest -q                                  # Everything
```
