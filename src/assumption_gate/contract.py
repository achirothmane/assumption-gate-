from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable

from .canonical import canonical_json_bytes as _canonical_json_bytes

CONTRACT_VERSION = "eba.integration/v0.1"
TEMPORAL_PROFILE_VERSION = "eba.temporal/v1"
CONTEXT_PROFILE_VERSION = "eba.context/v1"
CANONICAL_PROFILE_VERSION = "eba.canonical-json/v1"
MAX_SAFE_INTEGER = 9007199254740991
ASSUMPTION_KIND = "AssumptionState"


class ContractViolation(ValueError):
    pass


class AssumptionStatus(str, Enum):
    VALID = "VALID"
    STALE = "STALE"
    CONTRADICTED = "CONTRADICTED"
    UNKNOWN = "UNKNOWN"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_time(value: Any, *, field: str, allow_none: bool = True) -> datetime | None:
    if value is None:
        if allow_none:
            return None
        raise ContractViolation(f"{field.upper()}_MISSING")
    if not isinstance(value, str) or not value:
        raise ContractViolation(f"{field.upper()}_INVALID")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractViolation(f"{field.upper()}_INVALID") from exc
    if parsed.tzinfo is None:
        raise ContractViolation(f"{field.upper()}_INVALID")
    return parsed.astimezone(timezone.utc)


def canonical_json_bytes(value: dict[str, Any]) -> bytes:
    return _canonical_json_bytes(value, error=ContractViolation)


def _digest(value: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _stable_id(prefix: str, value: dict[str, Any]) -> str:
    return f"{prefix}_{_digest(value)[:24]}"


def _with_integrity(value: dict[str, Any]) -> dict[str, Any]:
    artifact = dict(value)
    artifact.pop("integrity", None)
    artifact["integrity"] = {
        "algorithm": "sha256",
        "digest": _digest(artifact),
    }
    return artifact


@dataclass(frozen=True)
class EvidenceRef:
    id: str
    verification: str
    observed_at: str | None = None
    valid_until: str | None = None


def evaluate_assumption(
    evidence: Iterable[EvidenceRef],
    *,
    now: str | None = None,
) -> tuple[AssumptionStatus, list[str]]:
    """Evaluate one required assumption using fail-closed Evidence-before-Action semantics.

    Rules:
    - any CONTRADICTED evidence -> CONTRADICTED
    - any expired supporting evidence -> STALE
    - at least one current VERIFIED evidence and no contradiction -> VALID
    - otherwise -> UNKNOWN
    """
    current = _parse_time(now or _utc_now(), field="evaluation_time", allow_none=False)
    assert current is not None

    items = list(evidence)
    if not items:
        return AssumptionStatus.UNKNOWN, ["EVIDENCE_MISSING"]

    reasons: list[str] = []
    verified_current = 0

    for item in items:
        verification = item.verification.upper()
        if verification == "CONTRADICTED":
            reasons.append(f"EVIDENCE_CONTRADICTED:{item.id}")
            continue
        if verification != "VERIFIED":
            reasons.append(f"EVIDENCE_UNVERIFIED:{item.id}")
            continue

        observed_at = _parse_time(item.observed_at, field="evidence_observed_at")
        if observed_at is not None and observed_at > current:
            reasons.append(f"EVIDENCE_FROM_FUTURE:{item.id}")
            continue

        valid_until = _parse_time(item.valid_until, field="evidence_valid_until")
        if valid_until is not None and current >= valid_until:
            reasons.append(f"EVIDENCE_EXPIRED:{item.id}")
            continue

        verified_current += 1

    if any(reason.startswith("EVIDENCE_CONTRADICTED:") for reason in reasons):
        return AssumptionStatus.CONTRADICTED, reasons

    if any(
        reason.startswith("EVIDENCE_EXPIRED:")
        or reason.startswith("EVIDENCE_FROM_FUTURE:")
        for reason in reasons
    ):
        return AssumptionStatus.STALE, reasons

    if verified_current > 0:
        return AssumptionStatus.VALID, []

    return AssumptionStatus.UNKNOWN, reasons or ["EVIDENCE_INSUFFICIENT"]


def build_assumption_state(
    *,
    assumption_id: str,
    proposition: str,
    evidence: Iterable[EvidenceRef],
    dependencies: Iterable[str] = (),
    trace_id: str,
    subject_ref: str,
    audience: str,
    namespace: str,
    producer: str = "assumption-gate",
    checked_at: str | None = None,
    valid_until: str | None = None,
) -> dict[str, Any]:
    if not assumption_id.strip():
        raise ContractViolation("assumption_id is required")
    if not proposition.strip():
        raise ContractViolation("proposition is required")
    if not trace_id.strip():
        raise ContractViolation("trace_id is required")
    if not subject_ref.strip():
        raise ContractViolation("subject_ref is required")
    if not audience.strip():
        raise ContractViolation("audience is required")
    if not namespace.strip():
        raise ContractViolation("namespace is required")

    checked_at = checked_at or _utc_now()
    checked_instant = _parse_time(checked_at, field="checked_at", allow_none=False)
    assert checked_instant is not None
    evidence_list = list(evidence)
    status, invalidation_reasons = evaluate_assumption(evidence_list, now=checked_at)

    requested_valid_until = _parse_time(
        valid_until,
        field="assumption_valid_until",
        allow_none=True,
    )
    supporting_expiries = [
        parsed
        for item in evidence_list
        if item.verification.upper() == "VERIFIED"
        for parsed in [
            _parse_time(
                item.valid_until,
                field="evidence_valid_until",
                allow_none=True,
            )
        ]
        if parsed is not None
    ]
    effective_valid_until = requested_valid_until
    if supporting_expiries:
        support_bound = min(supporting_expiries)
        if effective_valid_until is None or effective_valid_until > support_bound:
            effective_valid_until = support_bound

    artifact: dict[str, Any] = {
        "contract_version": CONTRACT_VERSION,
        "kind": ASSUMPTION_KIND,
        "temporal_profile": TEMPORAL_PROFILE_VERSION,
        "context_profile": CONTEXT_PROFILE_VERSION,
        "canonical_profile": CANONICAL_PROFILE_VERSION,
        "trace_id": trace_id,
        "subject_ref": subject_ref,
        "producer": producer,
        "trust": {
            "mode": "trusted_in_process",
            "issuer": producer,
            "audience": audience,
            "namespace": namespace,
        },
        "created_at": checked_at,
        "assumption_id": assumption_id,
        "proposition": proposition,
        "status": status.value,
        "evidence_refs": [item.id for item in evidence_list],
        "dependencies": sorted(set(dependencies)),
        "checked_at": checked_at,
        "valid_until": (
            effective_valid_until.isoformat(timespec="seconds").replace("+00:00", "Z")
            if effective_valid_until is not None
            else None
        ),
        "invalidation_reasons": invalidation_reasons,
    }
    artifact["id"] = _stable_id("as", artifact)
    return _with_integrity(artifact)


def validate_assumption_state(
    artifact: dict[str, Any],
    *,
    now: str | None = None,
    trace_id: str,
    subject_ref: str,
    audience: str,
    namespace: str,
    evidence_refs: Iterable[str] | None = None,
) -> None:
    if artifact.get("contract_version") != CONTRACT_VERSION:
        raise ContractViolation("unsupported contract_version")
    if artifact.get("kind") != ASSUMPTION_KIND:
        raise ContractViolation("expected AssumptionState")
    if artifact.get("status") != AssumptionStatus.VALID.value:
        raise ContractViolation(f"required assumption is {artifact.get('status')!r}")
    if artifact.get("context_profile") != CONTEXT_PROFILE_VERSION:
        raise ContractViolation("ASSUMPTION_CONTEXT_PROFILE_INVALID")
    if artifact.get("canonical_profile") != CANONICAL_PROFILE_VERSION:
        raise ContractViolation("ASSUMPTION_CANONICAL_PROFILE_INVALID")
    if artifact.get("trace_id") != trace_id:
        raise ContractViolation("ASSUMPTION_TRACE_MISMATCH")
    if artifact.get("subject_ref") != subject_ref:
        raise ContractViolation("ASSUMPTION_SUBJECT_MISMATCH")
    trust = artifact.get("trust")
    if not isinstance(trust, dict) or trust.get("mode") != "trusted_in_process":
        raise ContractViolation("ASSUMPTION_TRUST_ENVELOPE_INVALID")
    if trust.get("audience") != audience:
        raise ContractViolation("ASSUMPTION_AUDIENCE_MISMATCH")
    if trust.get("namespace") != namespace:
        raise ContractViolation("ASSUMPTION_NAMESPACE_MISMATCH")
    if evidence_refs is not None:
        expected_refs = list(evidence_refs)
        if artifact.get("evidence_refs") != expected_refs:
            raise ContractViolation("ASSUMPTION_EVIDENCE_BINDING_MISMATCH")

    if artifact.get("temporal_profile") not in {None, TEMPORAL_PROFILE_VERSION}:
        raise ContractViolation("ASSUMPTION_TEMPORAL_PROFILE_INVALID")

    current = _parse_time(now or _utc_now(), field="evaluation_time", allow_none=False)
    checked_at = _parse_time(
        artifact.get("checked_at"),
        field="assumption_checked_at",
        allow_none=False,
    )
    assert current is not None and checked_at is not None
    if checked_at > current:
        raise ContractViolation("ASSUMPTION_CHECKED_AT_FUTURE")
    if "valid_until" not in artifact:
        raise ContractViolation("ASSUMPTION_VALID_UNTIL_MISSING")
    valid_until = _parse_time(
        artifact.get("valid_until"),
        field="assumption_valid_until",
        allow_none=True,
    )
    if valid_until is not None and current >= valid_until:
        raise ContractViolation("ASSUMPTION_STALE")

    integrity = artifact.get("integrity")
    if not isinstance(integrity, dict) or integrity.get("algorithm") != "sha256":
        raise ContractViolation("missing SHA-256 integrity")
    expected = integrity.get("digest")
    unsigned = dict(artifact)
    unsigned.pop("integrity", None)
    if expected != _digest(unsigned):
        raise ContractViolation("ASSUMPTION_INTEGRITY_INVALID")
