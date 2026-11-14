"""Core data types shared by checks and renderers."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any


class Status(str, enum.Enum):
    """Outcome of a single diagnostic rule."""

    PASS = "PASS"  # noqa: S105 - not a password
    WARN = "WARN"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"
    SKIPPED = "SKIPPED"

    @property
    def severity(self) -> int:
        """Higher means more urgent; used for sorting summaries."""
        return {
            Status.FAIL: 4,
            Status.WARN: 3,
            Status.UNKNOWN: 2,
            Status.SKIPPED: 1,
            Status.PASS: 0,
        }[self]


class Confidence(str, enum.Enum):
    """How sure the tool is about a finding's conclusion."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class Finding:
    """One diagnostic result.

    ``verified`` is True only when the conclusion rests on deterministic local facts
    (e.g. "this email has no domain") or on data returned by GitHub. Everything else is
    a *possible explanation* and is labelled as such in every output format.
    """

    rule_id: str
    status: Status
    description: str
    confidence: Confidence
    verified: bool = False
    evidence: list[str] = field(default_factory=list)
    remediation: list[str] = field(default_factory=list)
    # Filled from the rule catalogue by the engine.
    title: str = ""
    category: str = ""
    explanation: str = ""
    docs: list[str] = field(default_factory=list)

    @property
    def is_issue(self) -> bool:
        return self.status in (Status.FAIL, Status.WARN)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.rule_id,
            "title": self.title,
            "category": self.category,
            "status": self.status.value,
            "confidence": self.confidence.value,
            "verified": self.verified,
            "description": self.description,
            "evidence": list(self.evidence),
            "remediation": list(self.remediation),
            "docs": list(self.docs),
            "explanation": self.explanation,
        }


@dataclass
class Report:
    """Full result of a scan."""

    tool_version: str
    generated_at: str
    repository: dict[str, Any]
    profile: dict[str, Any]
    scan: dict[str, Any]
    findings: list[Finding]

    def counts(self) -> dict[str, int]:
        result = {s.value: 0 for s in Status}
        for f in self.findings:
            result[f.status.value] += 1
        return result

    def issues(self) -> list[Finding]:
        """FAIL/WARN findings, most severe and most certain first."""
        order = {Confidence.HIGH: 0, Confidence.MEDIUM: 1, Confidence.LOW: 2}
        return sorted(
            (f for f in self.findings if f.is_issue),
            key=lambda f: (-f.status.severity, not f.verified, order[f.confidence]),
        )

    def to_dict(self) -> dict[str, Any]:
        issues = self.issues()
        return {
            "schema_version": 1,
            "tool": {"name": "github-contribution-doctor", "version": self.tool_version},
            "generated_at": self.generated_at,
            "read_only": True,
            "repository": self.repository,
            "profile": self.profile,
            "scan": self.scan,
            "summary": {
                "counts": self.counts(),
                "verified_issues": [f.rule_id for f in issues if f.verified],
                "possible_issues": [f.rule_id for f in issues if not f.verified],
                "note": (
                    "Commit counts are local observations of this clone, not GitHub "
                    "contribution counts."
                ),
            },
            "findings": [f.to_dict() for f in self.findings],
        }
