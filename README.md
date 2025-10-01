## Inspector (debug rule trees)

This repository includes a small inspector web app to inspect and debug the Oldcarts → OPD rule flows using the YAML files in `v1/`.

### Quickstart

1. Install (from repo root):

```bash
uv pip install -e .
```

2. Run the inspector:

```bash
prescreen-inspector
```

3. Open the browser at `http://localhost:8000`.

Use the dropdown to pick a symptom and choose a view mode:

- Combined: Oldcarts flow with a virtual OPD node connected to OPD entry
- Oldcarts: Only Oldcarts tree and OPD handoff
- OPD: Only OPD decision tree

Notes:

- The app reads YAML directly from `v1/rules/*.yaml` and constants from `v1/const/*.yaml`.
- Image assets under `v1/images/` are not required for visualization, but Oldcarts validations rely on their presence.



## Testing (pytest)

Run the unit tests locally with pytest.

Install dependencies (recommended):

```bash
uv pip install -e .
```

Execute all tests:

```bash
pytest -q
```

Run a specific test file or node id:

```bash
pytest tests/test_opd.py::test_opd_schema_and_parsing -q
```

Useful flags:

- `-q` quiet output
- `-k "pattern"` filter tests by substring
- `-x` stop on first failure

