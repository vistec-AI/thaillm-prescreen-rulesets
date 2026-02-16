## ThaiLLM Prescreen Ruleset

This repository contains rulesets used to gather information from patients to support prescreening features (triage and DDx). The rules are stored in the [`v1/`](./v1/) directory. The rules consist of the following procedure:

![prescreen-flow](./assets/diagram.png)


The ruleset contains three stages:
1. `ER`: Emergency rule-based stage. It consists of two sub-rules: ER symptom selection (early termination) and an ER checklist curated by doctors.
2. `OLDCARTS`: A fixed series of questions based on 16 NHSO symptoms, curated by doctors according to [OLDCARTS](https://www.onlinemeded.com/blog/oldcarts-acronym) principles.
3. `OPD`: Another fixed ruleset created with the goal of predicting assigned departments based on symptoms.

This repository also contains an inspector, allowing users to monitor the rules and edit them through the UI.

### Quickstart (Inspector)

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

Run a specific test file or node ID:

```bash
pytest tests/test_opd.py::test_opd_schema_and_parsing -q
```

Useful flags:

- `-q` quiet output
- `-k "pattern"` filter tests by substring
- `-x` stop on first failure

## Limitations

Although these rulesets are curated by doctors for research purposes, they carry many limitations and should be used with caution on the application side, especially in the medical domain where accuracy is critical for downstream applications.
- These rulesets are constructed based on 16 NHSO symptoms. If users present symptoms that are more specific than the provided 16 NHSO symptoms, the system may fail to gather accurate information.
- The DDx was designed only for research purposes, and the supported diseases are limited to [this list](./v1/const/diseases.yaml).
- When constructing the rules, we prioritized question coverage over simplicity, so some questions may be redundant.

## Authors
- **Chompakorn Chaksangchaichot**: Core Developer
- **Sukrit Sriratanawilai**: Researcher
- **Terasut Numwong**: Researcher, Medical Expert

We would like to extend our gratitude to every doctor who contributed to this program by curating a very thorough ruleset, as well as DEPA and BDI for sponsoring this research grant. This project is part of the ThaiLLM project.

