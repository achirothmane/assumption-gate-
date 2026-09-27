from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable

CONTRACT_VERSION = "eba.integration/v0.1"
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


def _parse_time(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractViolation(f"invalid timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        raise ContractViolation("timestamps must include timezone information")
    return parsed.astimezone(timezone.utc)


def canonical_json_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


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
    current = _parse_time(now or _utc_now())
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

        valid_until = _parse_time(item.valid_until)
        if valid_until is not None and current > valid_until:
            reasons.append(f"EVIDENCE_EXPIRED:{item.id}")
            continue

        verified_current += 1

    if any(reason.startswith("EVIDENCE_CONTRADICTED:") for reason in reasons):
        return AssumptionStatus.CONTRADICTED, reasons

    if any(reason.startswith("EVIDENCE_EXPIRED:") for reason in reasons):
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

    checked_at = checked_at or _utc_now()
    evidence_list = list(evidence)
    status, invalidation_reasons = evaluate_assumption(evidence_list, now=checked_at)

    artifact: dict[str, Any] = {
        "contract_version": CONTRACT_VERSION,
        "kind": ASSUMPTION_KIND,
        "trace_id": trace_id,
        "producer": producer,
        "created_at": checked_at,
        "assumption_id": assumption_id,
        "proposition": proposition,
        "status": status.value,
        "evidence_refs": [item.id for item in evidence_list],
        "dependencies": sorted(set(dependencies)),
        "checked_at": checked_at,
        "valid_until": valid_until,
        "invalidation_reasons": invalidation_reasons,
    }
    artifact["id"] = _stable_id("as", artifact)
    return _with_integrity(artifact)


def validate_assumption_state(
    artifact: dict[str, Any],
    *,
    now: str | None = None,
) -> None:
    if artifact.get("contract_version") != CONTRACT_VERSION:
        raise ContractViolation("unsupported contract_version")
    if artifact.get("kind") != ASSUMPTION_KIND:
        raise ContractViolation("expected AssumptionState")
    if artifact.get("status") != AssumptionStatus.VALID.value:
        raise ContractViolation(f"required assumption is {artifact.get('status')!r}")

    current = _parse_time(now or _utc_now())
    valid_until = _parse_time(artifact.get("valid_until"))
    if valid_until is not None and current is not None and current > valid_until:
        raise ContractViolation("ASSUMPTION_STALE")

    integrity = artifact.get("integrity")
    if not isinstance(integrity, dict) or integrity.get("algorithm") != "sha256":
        raise ContractViolation("missing SHA-256 integrity")
    expected = integrity.get("digest")
    unsigned = dict(artifact)
    unsigned.pop("integrity", None)
    if expected != _digest(unsigned):
        raise ContractViolation("ASSUMPTION_INTEGRITY_INVALID")
