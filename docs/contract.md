# AssumptionState contract profile

`assumption-gate` implements the `AssumptionState` slot of `eba.integration/v0.1`.

```json
{
  "contract_version": "eba.integration/v0.1",
  "kind": "AssumptionState",
  "id": "as_...",
  "trace_id": "tr_...",
  "producer": "assumption-gate",
  "created_at": "2026-09-27T16:00:00Z",
  "assumption_id": "ci.failure-is-transient",
  "proposition": "The observed CI failure is transient and safe to retry.",
  "status": "VALID",
  "evidence_refs": ["ev_..."],
  "dependencies": ["head-sha", "run-attempt"],
  "checked_at": "2026-09-27T16:00:00Z",
  "valid_until": "2026-09-27T16:05:00Z",
  "invalidation_reasons": [],
  "integrity": {
    "algorithm": "sha256",
    "digest": "..."
  }
}
```

Required consumers MUST fail closed for `STALE`, `CONTRADICTED`, and `UNKNOWN`.
