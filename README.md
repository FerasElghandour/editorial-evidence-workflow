# Editorial Evidence Workflow

**Feras Elghandour**

Maintain a content-research queue without turning popularity scores, missing metrics, or unsupported claims into automatic editorial approval.

## Implementation

A standard-library SQLite application with three source streams, seven qualification gates, thirteen scored dimensions, optimistic revisions, append-only history, preserved performance snapshots, and explicit editorial queue order. A companion calculator handles complete calendar windows and comparable-post baselines.

```mermaid
flowchart LR
 A[Research and original ideas] --> B[Evidence and originality gates]
 B --> C[Revisioned SQLite records]
 C --> D[Human editorial queue]
 D --> E[Immutable performance snapshots]
```

## Evidence and results

**21 tests pass**, covering failed-gate precedence, original contribution, source provenance, revision conflicts, immutable history, incomplete scores, missing performance values, timezone/DST windows, and duplicate-sample handling. Examples are synthetic; private research notes and account metrics are excluded.

## Run locally

Python 3.11 or later; use an isolated environment.

```sh
python -m unittest discover -s tests -v
python idea_engine.py --db local-data/demo.sqlite3 init
python idea_engine.py --db local-data/demo.sqlite3 put --file examples/qualified-idea.json --reason "Synthetic demonstration"
python idea_engine.py --db local-data/demo.sqlite3 list
python idea_engine.py --db local-data/demo.sqlite3 audit
```

A sanitized synthetic input snapshot is available in `idea-engine/initial-v2-snapshot.json`. Use the CLI help for database initialization, intake, revisions, queue selection, and performance recording. No social account, provider key, scraping, or posting action is required.

## Scope and limitations

This manages review and evidence. It does not establish audience growth, content quality, platform causality, or autonomous publishing. Scores remain editorial judgments and are constrained by explicit evidence gates.

[Validation record](VALIDATION.md) · [Inputs and applicable notices](DATA.md)
