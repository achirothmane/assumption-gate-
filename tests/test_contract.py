import copy

import pytest

from assumption_gate.contract import (
    AssumptionStatus,
    ContractViolation,
    EvidenceRef,
    build_assumption_state,
    evaluate_assumption,
    validate_assumption_state,
)

NOW = "2026-09-27T16:00:00Z"


def test_verified_current_evidence_makes_assumption_valid():
    status, reasons = evaluate_assumption(
        [EvidenceRef("ev_1", "VERIFIED", valid_until="2026-09-27T17:00:00Z")],
        now=NOW,
    )
    assert status is AssumptionStatus.VALID
    assert reasons == []


def test_missing_evidence_fails_closed_unknown():
    status, reasons = evaluate_assumption([], now=NOW)
    assert status is AssumptionStatus.UNKNOWN
    assert reasons == ["EVIDENCE_MISSING"]


def test_contradiction_dominates_support():
    status, reasons = evaluate_assumption(
        [
            EvidenceRef("ev_ok", "VERIFIED", valid_until="2026-09-27T17:00:00Z"),
            EvidenceRef("ev_bad", "CONTRADICTED"),
        ],
        now=NOW,
    )
    assert status is AssumptionStatus.CONTRADICTED
    assert "EVIDENCE_CONTRADICTED:ev_bad" in reasons


def test_expired_support_becomes_stale():
    status, reasons = evaluate_assumption(
        [EvidenceRef("ev_old", "VERIFIED", valid_until="2026-09-27T15:59:59Z")],
        now=NOW,
    )
    assert status is AssumptionStatus.STALE
    assert "EVIDENCE_EXPIRED:ev_old" in reasons


def test_assumption_state_matches_eba_contract_shape():
    state = build_assumption_state(
        assumption_id="ci.failure-is-transient",
        proposition="The observed CI failure is transient and safe to retry.",
        evidence=[EvidenceRef("ev_1", "VERIFIED", valid_until="2026-09-27T17:00:00Z")],
        dependencies=["run-attempt", "head-sha"],
        trace_id="tr_001",
        checked_at=NOW,
        valid_until="2026-09-27T16:05:00Z",
    )
    assert state["contract_version"] == "eba.integration/v0.1"
    assert state["kind"] == "AssumptionState"
    assert state["status"] == "VALID"
    assert state["evidence_refs"] == ["ev_1"]
    validate_assumption_state(state, now=NOW)


def test_tampering_breaks_integrity():
    state = build_assumption_state(
        assumption_id="ci.failure-is-transient",
        proposition="The observed CI failure is transient and safe to retry.",
        evidence=[EvidenceRef("ev_1", "VERIFIED")],
        trace_id="tr_001",
        checked_at=NOW,
    )
    tampered = copy.deepcopy(state)
    tampered["proposition"] = "changed after publication"
    with pytest.raises(ContractViolation, match="INTEGRITY"):
        validate_assumption_state(tampered, now=NOW)


def test_required_non_valid_state_cannot_pass_gate():
    state = build_assumption_state(
        assumption_id="ci.failure-is-transient",
        proposition="The observed CI failure is transient and safe to retry.",
        evidence=[],
        trace_id="tr_001",
        checked_at=NOW,
    )
    with pytest.raises(ContractViolation, match="UNKNOWN"):
        validate_assumption_state(state, now=NOW)
