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
    qid="demographics",    # phase marker (bulk) or question ID (sequential)
    value={...},            # full batch (bulk) or single answer (sequential)
)
```

#### Submitting Answers Per Phase

Each phase expects a different `qid` and `value` shape:

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
# qid is the specific question ID from the previous step
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

## Package Layout

```
src/prescreen_rulesets/
├── __init__.py          # Public exports
├── engine.py            # PrescreenEngine — orchestrator
├── ruleset.py           # RulesetStore — YAML loading + lookups
├── evaluator.py         # ConditionalEvaluator — auto-eval logic
├── constants.py         # Shared constants (severity order, phase names, defaults)
└── models/
    ├── __init__.py      # Re-exports all model classes
    ├── action.py        # GotoAction, OPDAction, TerminateAction
    ├── question.py      # 10 question types + Question union + question_mapper
    ├── schema.py        # DepartmentConst, SeverityConst, NHSOSymptom, etc.
    └── session.py       # StepResult, QuestionsStep, TerminationStep, SessionInfo
```

## Testing

```bash
uv run pytest tests/test_ruleset_store.py -q     # RulesetStore smoke tests
uv run pytest tests/test_evaluator.py -q          # Evaluator unit tests
uv run pytest tests/test_tree_walkthrough.py -q   # Tree walkthrough (all symptoms)
uv run pytest tests/test_engine.py -q             # Engine with mocked DB
uv run pytest -q                                  # Everything
```
