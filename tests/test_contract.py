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
TRACE = "tr_001"
SUBJECT = "req_001"
AUDIENCE = "workflow-failure-lab/ci-retry-gate"
NAMESPACE = "github-repository:achirothmane/workflow-failure-lab"


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
        trace_id=TRACE,
        subject_ref=SUBJECT,
        audience=AUDIENCE,
        namespace=NAMESPACE,
        checked_at=NOW,
        valid_until="2026-09-27T16:05:00Z",
    )
    assert state["contract_version"] == "eba.integration/v0.1"
    assert state["kind"] == "AssumptionState"
    assert state["status"] == "VALID"
    assert state["evidence_refs"] == ["ev_1"]
    validate_assumption_state(
        state,
        now=NOW,
        trace_id=TRACE,
        subject_ref=SUBJECT,
        audience=AUDIENCE,
        namespace=NAMESPACE,
    )




def test_exact_expiry_is_stale():
    status, reasons = evaluate_assumption(
        [EvidenceRef("ev_1", "VERIFIED", valid_until=NOW)],
        now=NOW,
    )
    assert status is AssumptionStatus.STALE
    assert reasons == ["EVIDENCE_EXPIRED:ev_1"]


def test_future_observation_is_stale():
    status, reasons = evaluate_assumption(
        [EvidenceRef("ev_1", "VERIFIED", observed_at="2026-09-27T16:00:01Z")],
        now=NOW,
    )
    assert status is AssumptionStatus.STALE
    assert reasons == ["EVIDENCE_FROM_FUTURE:ev_1"]


def test_derived_state_cannot_outlive_finite_support():
    state = build_assumption_state(
        assumption_id="ci.failure-is-transient",
        proposition="The observed CI failure is transient and safe to retry.",
        evidence=[
            EvidenceRef(
                "ev_1",
                "VERIFIED",
                valid_until="2026-09-27T16:05:00Z",
            )
        ],
        trace_id=TRACE,
        subject_ref=SUBJECT,
        audience=AUDIENCE,
        namespace=NAMESPACE,
        checked_at=NOW,
        valid_until=None,
    )
    assert state["valid_until"] == "2026-09-27T16:05:00Z"
    validate_assumption_state(
        state,
        now="2026-09-27T16:04:59Z",
        trace_id=TRACE,
        subject_ref=SUBJECT,
        audience=AUDIENCE,
        namespace=NAMESPACE,
    )
    with pytest.raises(ContractViolation, match="ASSUMPTION_STALE"):
        validate_assumption_state(
            state,
            now="2026-09-27T16:05:00Z",
            trace_id=TRACE,
            subject_ref=SUBJECT,
            audience=AUDIENCE,
            namespace=NAMESPACE,
        )


def test_requested_validity_is_capped_by_support():
    state = build_assumption_state(
        assumption_id="ci.failure-is-transient",
        proposition="The observed CI failure is transient and safe to retry.",
        evidence=[
            EvidenceRef(
                "ev_1",
                "VERIFIED",
                valid_until="2026-09-27T16:05:00Z",
            )
        ],
        trace_id=TRACE,
        subject_ref=SUBJECT,
        audience=AUDIENCE,
        namespace=NAMESPACE,
        checked_at=NOW,
        valid_until="2026-09-27T17:00:00Z",
    )
    assert state["valid_until"] == "2026-09-27T16:05:00Z"


def test_malformed_valid_until_is_rejected():
    state = build_assumption_state(
        assumption_id="ci.failure-is-transient",
        proposition="The observed CI failure is transient and safe to retry.",
        evidence=[EvidenceRef("ev_1", "VERIFIED")],
        trace_id=TRACE,
        subject_ref=SUBJECT,
        audience=AUDIENCE,
        namespace=NAMESPACE,
        checked_at=NOW,
    )
    malformed = copy.deepcopy(state)
    malformed["valid_until"] = 123
    unsigned = dict(malformed)
    unsigned.pop("integrity", None)
    import hashlib, json
    malformed["integrity"] = {
        "algorithm": "sha256",
        "digest": hashlib.sha256(
            json.dumps(
                unsigned,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest(),
    }
    with pytest.raises(ContractViolation, match="ASSUMPTION_VALID_UNTIL_INVALID"):
        validate_assumption_state(
            malformed,
            now=NOW,
            trace_id=TRACE,
            subject_ref=SUBJECT,
            audience=AUDIENCE,
            namespace=NAMESPACE,
        )




def test_rehashed_context_substitution_is_rejected():
    state = build_assumption_state(
        assumption_id="ci.failure-is-transient",
        proposition="The observed CI failure is transient and safe to retry.",
        evidence=[EvidenceRef("ev_1", "VERIFIED")],
        trace_id=TRACE,
        subject_ref=SUBJECT,
        audience=AUDIENCE,
        namespace=NAMESPACE,
        checked_at=NOW,
    )
    edited = copy.deepcopy(state)
    edited["subject_ref"] = "req_other"
    unsigned = dict(edited)
    unsigned.pop("integrity", None)
    import hashlib, json
    edited["integrity"] = {
        "algorithm": "sha256",
        "digest": hashlib.sha256(
            json.dumps(
                unsigned,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest(),
    }
    with pytest.raises(ContractViolation, match="ASSUMPTION_SUBJECT_MISMATCH"):
        validate_assumption_state(
            edited,
            now=NOW,
            trace_id=TRACE,
            subject_ref=SUBJECT,
            audience=AUDIENCE,
            namespace=NAMESPACE,
        )


def test_projection_is_declared_local_not_easl_graph_equivalence():
    state = build_assumption_state(
        assumption_id="ci.failure-is-transient",
        proposition="The observed CI failure is transient and safe to retry.",
        evidence=[EvidenceRef("ev_1", "VERIFIED")],
        trace_id=TRACE,
        subject_ref=SUBJECT,
        audience=AUDIENCE,
        namespace=NAMESPACE,
        checked_at=NOW,
    )
    assert state["trust"]["mode"] == "trusted_in_process"
    assert state["context_profile"] == "eba.context/v1"


def test_tampering_breaks_integrity():
    state = build_assumption_state(
        assumption_id="ci.failure-is-transient",
        proposition="The observed CI failure is transient and safe to retry.",
        evidence=[EvidenceRef("ev_1", "VERIFIED")],
        trace_id=TRACE,
        subject_ref=SUBJECT,
        audience=AUDIENCE,
        namespace=NAMESPACE,
        checked_at=NOW,
    )
    tampered = copy.deepcopy(state)
    tampered["proposition"] = "changed after publication"
    with pytest.raises(ContractViolation, match="INTEGRITY"):
        validate_assumption_state(
            tampered,
            now=NOW,
            trace_id=TRACE,
            subject_ref=SUBJECT,
            audience=AUDIENCE,
            namespace=NAMESPACE,
        )


def test_required_non_valid_state_cannot_pass_gate():
    state = build_assumption_state(
        assumption_id="ci.failure-is-transient",
        proposition="The observed CI failure is transient and safe to retry.",
        evidence=[],
        trace_id=TRACE,
        subject_ref=SUBJECT,
        audience=AUDIENCE,
        namespace=NAMESPACE,
        checked_at=NOW,
    )
    with pytest.raises(ContractViolation, match="UNKNOWN"):
        validate_assumption_state(
        state,
        now=NOW,
        trace_id=TRACE,
        subject_ref=SUBJECT,
        audience=AUDIENCE,
        namespace=NAMESPACE,
    )
