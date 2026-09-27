# assumption-gate

A small, fail-closed Evidence-before-Action primitive that decides whether a required operational assumption is still valid **at decision time**.

It does not decide whether an action is authorized. It produces a machine-readable `AssumptionState` that another enforcement layer can consume.

## Why it exists

Operational systems often continue acting on assumptions that were once true:

- a deployment target is unchanged;
- a dependency is still healthy;
- a CI failure is transient;
- a credential or policy context is still valid;
- a human approval still refers to the current state.

`assumption-gate` makes those assumptions explicit and fail-closed.

## Contract

This implementation emits `AssumptionState` artifacts compatible with:

`eba.integration/v0.1`

States are:

- `VALID`
- `STALE`
- `CONTRADICTED`
- `UNKNOWN`

For a required assumption, only `VALID` may proceed.

## Minimal example

```python
from assumption_gate.contract import EvidenceRef, build_assumption_state

state = build_assumption_state(
    assumption_id="ci.failure-is-transient",
    proposition="The observed CI failure is transient and safe to retry.",
    evidence=[
        EvidenceRef(
            id="ev_123",
            verification="VERIFIED",
            valid_until="2026-09-27T17:00:00Z",
        )
    ],
    trace_id="tr_123",
)

assert state["status"] == "VALID"
```

## Design boundary

`assumption-gate` owns assumption validity, not identity, authorization, budgets, execution, or policy orchestration.

```text
Evidence / EASL
      ↓
assumption-gate
      ↓
AssumptionState
      ↓
Aegis-EGE / action guard / other enforcement layer
      ↓
Decision
```

## Invariants

1. Missing required evidence does not become permission.
2. Contradiction dominates supporting evidence.
3. Expired support makes an assumption stale.
4. Published artifacts are integrity-bound.
5. A material change requires a new artifact.
6. Only `VALID` satisfies a required assumption gate.

## Development

```bash
python -m pip install -e .[test]
pytest -q
```
